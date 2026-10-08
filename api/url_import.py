"""Import vehicle photographs from a listing URL."""

from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import json
import logging
import mimetypes
import os
import re
import socket
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image

logger = logging.getLogger("autopivot.url_import")

MAX_IMAGES = 20
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_BYTES = 2 * 1024          # skips tracking pixels and spacer gifs

MIN_IMAGE_PIXELS = int(os.getenv("URL_IMPORT_MIN_IMAGE_PIXELS", "200"))

MAX_PAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 10.0
CONCURRENT_DOWNLOADS = 6

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AutoPivotImageImporter/1.0)",
    "Accept": "text/html,application/xhtml+xml,image/*;q=0.8,*/*;q=0.5",
}

KNOWN_UNSUPPORTED: dict[str, str] = {
    "carsales.com.au": "carsales blocks automated requests, so its photographs cannot be imported.",
    "www.carsales.com.au": "carsales blocks automated requests, so its photographs cannot be imported.",
    "autotrader.com.au": "autotrader builds its gallery in the browser, so the page we receive holds no vehicle photographs.",
    "www.autotrader.com.au": "autotrader builds its gallery in the browser, so the page we receive holds no vehicle photographs.",
}

ALLOWED_HOSTS: frozenset[str] = frozenset(
    h.strip().lower()
    for h in os.getenv("URL_IMPORT_ALLOWED_HOSTS", "").split(",")
    if h.strip()
)


class UrlImportError(Exception):
    """Carries a message intended to be shown to the person who pasted the URL."""


# ── Vehicle guess from the URL itself ───────────────────────────────────────
_CAR_SLUG_RE = re.compile(r"/car/\d+/([a-z0-9.-]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_SLUG_ID_RE = re.compile(r"^[a-z]{0,4}\d{4,}[a-z0-9]*$", re.IGNORECASE)
_SLUG_MAX_MODEL_WORDS = 2


@dataclass
class VehicleGuess:
    year: int
    make: str
    model: str
    variant: str | None = None


def _title_word(token: str) -> str:
    return token.upper() if any(c.isdigit() for c in token) else token.capitalize()


def _make_tokens() -> list[tuple[list[str], str]]:
    pairs = []
    for make in MAKES:
        tokens = re.split(r"[\s\-]+", make.lower())
        pairs.append((tokens, make))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


def _guess_from_any_slug(path: str) -> VehicleGuess | None:
    segments = [s for s in path.split("/") if s]
    for segment in reversed(segments):
        tokens = [t for t in segment.lower().split("-") if t]
        for i, token in enumerate(tokens):
            if not _YEAR_RE.match(token):
                continue
            year = int(token)
            if not (MIN_PLAUSIBLE_YEAR <= year <= _year_ceiling()):
                continue
            rest = tokens[i + 1:]
            for make_tokens, make in _make_tokens():
                if rest[: len(make_tokens)] != make_tokens:
                    continue
                model_tokens: list[str] = []
                for t in rest[len(make_tokens):]:
                    if _SLUG_ID_RE.match(t):
                        break
                    model_tokens.append(t)
                    if len(model_tokens) >= _SLUG_MAX_MODEL_WORDS:
                        break
                if not model_tokens:
                    return None
                return VehicleGuess(
                    year=year,
                    make=make,
                    model=" ".join(_title_word(t) for t in model_tokens),
                )
    return None


def guess_vehicle_from_url(url: str) -> VehicleGuess | None:
    """Guess year/make/model/variant from a listing URL's own slug."""
    path = urlparse(url).path
    match = _CAR_SLUG_RE.search(path)
    if match:
        tokens = [t for t in match.group(1).split("-") if t]
        if len(tokens) < 3 or not _YEAR_RE.match(tokens[0]):
            return None
        variant = " ".join(tokens[3:]).strip() or None
        return VehicleGuess(
            year=int(tokens[0]),
            make=tokens[1].capitalize(),
            model=tokens[2].capitalize(),
            variant=variant,
        )
    return _guess_from_any_slug(path)


@dataclass
class FetchedImage:
    filename: str
    content_type: str
    content: bytes

    def as_payload(self) -> dict:
        """Base64 form, for the unauthenticated processing endpoint."""
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "data": base64.b64encode(self.content).decode("ascii"),
        }


@dataclass
class VehicleDetails:
    """Best-effort make, model, year, variant and stock number for the vehicle a listing
    page is about — see `extract_vehicle_details`.
    """

    make: str | None = None
    model: str | None = None
    year: int | None = None
    variant: str | None = None
    stock_number: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (self.make, self.model, self.year, self.variant, self.stock_number)
        )


@dataclass
class ImportResult:
    images: list[FetchedImage] = field(default_factory=list)
    note: str | None = None
    vehicle: VehicleDetails | None = None


# ── Host policy ────────────────────────────────────────────────────────────────

def is_safe_host(hostname: str | None) -> bool:
    """Reject hostnames resolving to private, loopback, link-local or reserved IPs."""
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def check_host_policy(hostname: str | None) -> None:
    """Raise UrlImportError if this host is one we already know will not work."""
    host = (hostname or "").lower()

    if host in KNOWN_UNSUPPORTED:
        raise UrlImportError(KNOWN_UNSUPPORTED[host])

    for known, reason in KNOWN_UNSUPPORTED.items():
        if host.endswith("." + known):
            raise UrlImportError(reason)

    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        raise UrlImportError(
            "Importing from this site is not enabled. "
            "Download the photographs and upload them instead."
        )


# ── HTML parsing ───────────────────────────────────────────────────────────────

def extract_image_urls(html: str, base_url: str) -> list[str]:
    """Collect candidate image URLs from a page. Parser by Akhanda Bhandari."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []

    def add(candidate: str | None) -> None:
        if not candidate:
            return
        candidate = candidate.strip()
        if not candidate or candidate.startswith("data:"):
            return
        absolute = urljoin(base_url, candidate)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or absolute in seen:
            return
        seen.add(absolute)
        urls.append(absolute)

    for img in soup.find_all("img"):
        add(img.get("src"))
        add(img.get("data-src"))       # common lazy-load attributes
        add(img.get("data-lazy-src"))
        srcset = img.get("srcset")
        if srcset:
            add(srcset.split(",")[0].strip().split(" ")[0])

    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if srcset:
            add(srcset.split(",")[0].strip().split(" ")[0])

    if not urls:
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            add(og_image["content"])

    return urls


def filename_from_url(url: str, fallback_index: int, ext: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
    if not name or "." not in name:
        name = f"url-image-{fallback_index + 1}{ext}"
    return name


# ── Vehicle details ────────────────────────────────────────────────────────────

MIN_PLAUSIBLE_YEAR = 1950
MAX_YEAR_AHEAD = 1

MAKES: tuple[str, ...] = (
    "Toyota", "Honda", "Nissan", "Mazda", "Mitsubishi", "Subaru", "Suzuki",
    "Daihatsu", "Lexus", "Isuzu", "Acura", "Infiniti",
    "Ford", "Holden", "Chevrolet", "Chrysler", "Dodge", "Jeep", "Ram", "GMC",
    "Cadillac", "Lincoln", "Buick", "Tesla",
    "BMW", "Mercedes-Benz", "Mercedes", "Audi", "Volkswagen", "Porsche",
    "Opel", "Smart",
    "Hyundai", "Kia", "Genesis", "SsangYong",
    "Volvo", "Saab", "Peugeot", "Renault", "Citroen", "Citroën", "Fiat",
    "Alfa Romeo", "Skoda", "Seat", "Land Rover", "Range Rover", "Jaguar",
    "Mini", "Bentley", "Rolls-Royce", "Aston Martin", "McLaren", "Lotus",
    "Ferrari", "Lamborghini", "Maserati",
    "MG", "Great Wall", "GWM", "Haval", "Chery", "BYD", "LDV",
)
_MAKES_LONGEST_FIRST: tuple[str, ...] = tuple(sorted(MAKES, key=len, reverse=True))


def _year_ceiling() -> int:
    return date.today().year + MAX_YEAR_AHEAD


def _year_from_text(text: str) -> int | None:
    """The first plausible-looking model year in `text`, read left to right."""
    ceiling = _year_ceiling()
    for match in re.finditer(r"(?:19|20)\d{2}", text):
        year = int(match.group())
        if MIN_PLAUSIBLE_YEAR <= year <= ceiling:
            return year
    return None


def _stock_number_from_text(text: str) -> str | None:
    match = re.search(
        r"stock\s*(?:id|no\.?|number|#)?\s*[:\-]?\s*([A-Za-z0-9\-]{3,20})",
        text, re.IGNORECASE,
    )
    return match.group(1).strip().upper() if match else None


def _make_and_model_from_text(text: str) -> tuple[str | None, str | None]:
    """The longest known make that appears in `text`, and whatever word or two
    immediately follows it, up to the next digit or separator.
    """
    for make in _MAKES_LONGEST_FIRST:
        match = re.search(re.escape(make), text, re.IGNORECASE)
        if not match:
            continue
        remainder = text[match.end():].strip(" |·,-")
        model_match = re.match(
            r"(?:[A-Za-z][A-Za-z0-9\-]*|\d{1,4}(?![\d,.]))"
            r"(?:\s+(?!(?:for|sale|used|new|demo)\b)[A-Za-z][A-Za-z0-9\-]*){0,3}",
            remainder, re.IGNORECASE,
        )
        model = model_match.group(0).strip() if model_match else None
        return make, (model or None)
    return None, None


def _split_model_and_variant(model: str | None) -> tuple[str | None, str | None]:
    """'5008 GT Line Wagon' -> ('5008', 'GT Line Wagon')."""
    if not model:
        return model, None
    first, _, rest = model.partition(" ")
    if rest and any(ch.isdigit() for ch in first):
        return first, rest.strip() or None
    return model, None


def _flatten_json_ld(data: object) -> list[dict]:
    """JSON-LD can be one object, a list of them, or an @graph of them."""
    if isinstance(data, list):
        nodes = data
    elif isinstance(data, dict) and isinstance(data.get("@graph"), list):
        nodes = data["@graph"]
    elif isinstance(data, dict):
        nodes = [data]
    else:
        nodes = []
    return [n for n in nodes if isinstance(n, dict)]


def _vehicle_details_from_json_ld_node(node: dict) -> VehicleDetails | None:
    node_type = node.get("@type")
    types = {node_type} if isinstance(node_type, str) else set(node_type or [])
    if not types & {"Car", "Vehicle", "Product"}:
        return None

    def text(value: object) -> str | None:
        if isinstance(value, dict):
            value = value.get("name")
        return str(value).strip() if value else None

    make = text(node.get("brand")) or text(node.get("manufacturer"))
    model = text(node.get("model"))

    year = None
    for key in ("vehicleModelDate", "productionDate", "releaseDate", "modelDate"):
        year = _year_from_text(str(node.get(key) or ""))
        if year:
            break
    if year is None:
        year = _year_from_text(text(node.get("name")) or "")

    stock_number = (
        text(node.get("sku")) or text(node.get("mpn")) or text(node.get("productID"))
    )

    details = VehicleDetails(make=make, model=model, year=year, stock_number=stock_number)
    return None if details.is_empty() else details


def _vehicle_details_from_json_ld(html: str) -> VehicleDetails | None:
    """schema.org Car/Vehicle/Product markup, when a listing page carries it."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (TypeError, ValueError):
            continue
        for node in _flatten_json_ld(data):
            details = _vehicle_details_from_json_ld_node(node)
            if details is not None:
                return details
    return None


def extract_vehicle_details(html: str) -> VehicleDetails | None:
    """Best-effort make, model, year and stock number for the vehicle a listing page is
    about.
    """
    from_structured_data = _vehicle_details_from_json_ld(html)
    if from_structured_data is not None:
        return from_structured_data

    soup = BeautifulSoup(html, "html.parser")
    texts: list[str] = []
    if soup.title and soup.title.string:
        texts.append(soup.title.string)
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        texts.append(og_title["content"])
    og_description = soup.find("meta", property="og:description")
    if og_description and og_description.get("content"):
        texts.append(og_description["content"])

    combined = " | ".join(t.strip() for t in texts if t and t.strip())
    if not combined:
        return None

    make, model = _make_and_model_from_text(combined)
    model, variant = _split_model_and_variant(model)
    details = VehicleDetails(
        make=make,
        model=model,
        variant=variant,
        year=_year_from_text(combined),
        stock_number=_stock_number_from_text(combined),
    )
    return None if details.is_empty() else details


def is_large_enough(content: bytes) -> bool:
    """True if both sides of the image reach MIN_IMAGE_PIXELS."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except Exception:
        return False
    return min(width, height) >= MIN_IMAGE_PIXELS


def _build(source_url: str, content: bytes, content_type: str, index: int) -> FetchedImage | None:
    if not content:
        return None
    ext = (
        ALLOWED_IMAGE_TYPES.get(content_type)
        or mimetypes.guess_extension(content_type)
        or ".jpg"
    )
    return FetchedImage(
        filename=filename_from_url(source_url, index, ext),
        content_type=content_type,
        content=content,
    )


# ── Fetch ──────────────────────────────────────────────────────────────────────

async def fetch_vehicle_details(url: str) -> VehicleDetails | None:
    """Fetch a listing page and return whatever `extract_vehicle_details` can read from
    it, without downloading any of its photographs.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise UrlImportError("Enter a full address beginning http:// or https://.")

    check_host_policy(parsed.hostname)
    if not is_safe_host(parsed.hostname):
        raise UrlImportError("That address cannot be reached from the server.")

    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS, timeout=FETCH_TIMEOUT, follow_redirects=True,
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.info(
                "Vehicle-details fetch could not reach %s: %s", parsed.hostname, exc
            )
            raise UrlImportError("That page could not be reached.") from exc

        if response.status_code in (401, 403, 429):
            raise UrlImportError(
                "That site blocks automated requests, so its details could "
                "not be read."
            )
        if response.status_code >= 400:
            raise UrlImportError(
                f"That page responded with status {response.status_code}."
            )

        final_host = urlparse(str(response.url)).hostname
        check_host_policy(final_host)
        if not is_safe_host(final_host):
            raise UrlImportError("That address cannot be reached from the server.")

        content_type = (
            response.headers.get("content-type", "").split(";")[0].strip().lower()
        )
        if "html" not in content_type:
            return None
        if len(response.content) > MAX_PAGE_BYTES:
            raise UrlImportError("That page is too large to scan.")

        return extract_vehicle_details(response.text)


async def fetch_images(url: str) -> ImportResult:
    """Fetch a listing page and return the vehicle photographs found on it."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise UrlImportError("Enter a full address beginning http:// or https://.")

    check_host_policy(parsed.hostname)
    if not is_safe_host(parsed.hostname):
        raise UrlImportError("That address cannot be reached from the server.")

    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS,
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=CONCURRENT_DOWNLOADS),
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.info("URL import could not reach %s: %s", parsed.hostname, exc)
            raise UrlImportError("That page could not be reached.") from exc

        if response.status_code in (401, 403, 429):
            raise UrlImportError(
                "That site blocks automated requests, so its photographs cannot "
                "be imported. Download them and upload them instead."
            )
        if response.status_code >= 400:
            raise UrlImportError(
                f"That page responded with status {response.status_code}."
            )

        final_host = urlparse(str(response.url)).hostname
        check_host_policy(final_host)
        if not is_safe_host(final_host):
            raise UrlImportError("That address cannot be reached from the server.")

        content_type = (
            response.headers.get("content-type", "").split(";")[0].strip().lower()
        )

        if content_type in ALLOWED_IMAGE_TYPES:
            entry = _build(str(response.url), response.content, content_type, 0)
            return ImportResult(images=[entry] if entry else [])

        if "html" not in content_type:
            raise UrlImportError(
                "That address is neither a webpage nor an image we can read."
            )

        if len(response.content) > MAX_PAGE_BYTES:
            raise UrlImportError("That page is too large to scan.")

        vehicle = extract_vehicle_details(response.text)

        candidates = extract_image_urls(response.text, base_url=str(response.url))
        if not candidates:
            raise UrlImportError(
                "No photographs were found on that page. Sites that build their "
                "gallery in the browser cannot be imported this way."
            )

        candidates = candidates[: MAX_IMAGES * 2]
        semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

        async def fetch_one(image_url: str, index: int) -> FetchedImage | None:
            if not is_safe_host(urlparse(image_url).hostname):
                return None
            async with semaphore:
                try:
                    reply = await client.get(image_url)
                except httpx.HTTPError:
                    return None
            if reply.status_code >= 400:
                return None
            ctype = reply.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in ALLOWED_IMAGE_TYPES:
                return None
            if not MIN_IMAGE_BYTES <= len(reply.content) <= MAX_IMAGE_BYTES:
                return None
            if not is_large_enough(reply.content):
                return None
            return _build(image_url, reply.content, ctype, index)

        fetched = await asyncio.gather(
            *[fetch_one(u, i) for i, u in enumerate(candidates)]
        )
        images = [entry for entry in fetched if entry][:MAX_IMAGES]

        if not images:
            raise UrlImportError(
                "Photographs were listed on that page but none could be "
                "downloaded. Download them and upload them instead."
            )

        note = (
            "Imported photographs are whatever the page published, so check "
            "them before processing — site logos and banners can come through "
            "alongside the vehicle."
        )
        logger.info(
            "URL import — host=%s candidates=%d imported=%d vehicle=%s",
            parsed.hostname, len(candidates), len(images), vehicle is not None,
        )
        return ImportResult(images=images, note=note, vehicle=vehicle)

