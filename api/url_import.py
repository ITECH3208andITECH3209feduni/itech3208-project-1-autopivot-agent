"""Import vehicle photographs from a listing URL.

The fetching, SSRF guard and HTML parsing are Akhanda Bhandari's work, lifted
out of autopivot_backend.py so the light API can use them without importing
torch. Both halves now call this module rather than keeping two copies.

Added here: a host policy and failure messages that name the actual cause.

This does not work on every site, and that is not a bug we can fix from our
side. Two patterns defeat it:

  * A WAF answers an automated request with 403 or 429 no matter how the
    request is shaped. carsales.com.au does this.
  * The page ships an empty shell and paints the gallery with JavaScript, so
    the HTML we receive holds the site's own logos and nothing else.
    autotrader.com.au does this.

Both were confirmed by hand against the live sites. Rather than return "no
images found" and let a dealer conclude their listing is broken, each known
case is named, and unknown hosts get a message describing which of the two
they hit.
"""

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

# The byte floor alone lets page furniture through: a 2cheapcars import brought
# in bluecorner.png at 105x81 and star-4.png at 210x71, both comfortably over
# 2 KB and neither of them a photograph of anything. Measured on the shorter
# side, because a badge is wide and short. 200 clears both of those by a wide
# margin and is still below anything a gallery would publish as a photograph;
# raise it through the environment if a site turns out to serve small
# thumbnails in its HTML alongside the real images.
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

# Verified by hand. The value is shown to the user, so it says what the site
# does rather than what we would like it to do.
KNOWN_UNSUPPORTED: dict[str, str] = {
    "carsales.com.au": "carsales blocks automated requests, so its photographs cannot be imported.",
    "www.carsales.com.au": "carsales blocks automated requests, so its photographs cannot be imported.",
    "autotrader.com.au": "autotrader builds its gallery in the browser, so the page we receive holds no vehicle photographs.",
    "www.autotrader.com.au": "autotrader builds its gallery in the browser, so the page we receive holds no vehicle photographs.",
}

# Optional allowlist. Empty means "try any host that is not known-unsupported",
# which is the useful default while we are still learning which sites work.
# Set URL_IMPORT_ALLOWED_HOSTS to lock it down for a deployment.
ALLOWED_HOSTS: frozenset[str] = frozenset(
    h.strip().lower()
    for h in os.getenv("URL_IMPORT_ALLOWED_HOSTS", "").split(",")
    if h.strip()
)


class UrlImportError(Exception):
    """Carries a message intended to be shown to the person who pasted the URL."""


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
    """
    Best-effort make, model, year, variant and stock number for the vehicle a
    listing page is about — see `extract_vehicle_details`. Every field is
    None rather than guessed when nothing reliable was found; the dealer
    fills it in by hand exactly as they would if this did not exist.
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
    """
    Reject hostnames resolving to private, loopback, link-local or reserved IPs.

    SSRF guard by Akhanda Bhandari. Without it a pasted URL is a way to make
    the server fetch its own metadata service or anything else on the pod's
    network and hand back the response.
    """
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

    # Also catch subdomains of a known-unsupported registrable domain.
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
# A listing page was written for a person to read, not a machine to parse, so
# this is best-effort in the same spirit as the image scraping above: what it
# finds pre-fills an editable form field, never a saved record, and finding
# nothing is a normal, expected result rather than a failure.

MIN_PLAUSIBLE_YEAR = 1950
# A dealer photographing next year's model before the calendar turns is a
# real listing, not a typo — the ceiling allows for it rather than rejecting
# the one case a strict "no later than today" rule would get wrong.
MAX_YEAR_AHEAD = 1

# Common manufacturers across both JDM-import stock (this module's first use)
# and mainstream Australian/NZ dealer stock. Matched case-insensitively
# against page text — see _make_and_model_from_text — and spelled the way a
# dealer would write it rather than as a legal entity name. Longest names
# first so "Land Rover" is tried before a shorter make could be mistaken for
# part of it; MAKES itself stays in a natural, readable order and the sort
# happens once at import time.
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
    """The first plausible-looking model year in `text`, read left to right.

    Matched as exactly two digits after "19" or "20" rather than any 4-digit
    run, so a mileage or a price does not get mistaken for one; scanned in
    reading order and the first in range wins, because a listing's own model
    year is almost always mentioned before an unrelated year buried in
    boilerplate ("...a trusted dealer since 1993").
    """
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
    # Stock numbers are conventionally shouted (SBT's own pages mix "Stock
    # Id:DBE6495" with "stock dbe6495" in different spots) — normalise so the
    # same plate always reads the same way regardless of which spot matched.
    return match.group(1).strip().upper() if match else None


def _make_and_model_from_text(text: str) -> tuple[str | None, str | None]:
    """
    The longest known make that appears in `text`, and whatever word or two
    immediately follows it, up to the next digit or separator.

    A listing title reads like "2006/4 HONDA ACCORD 165554 | Stock Id:..." —
    make and model sit next to each other with nothing marking where one
    ends and the other begins, so this takes the model to be a run of
    letter-led words (each may carry trailing digits/hyphens of its own,
    e.g. "C200") separated by single spaces, stopping at the first token
    that is itself a bare number — a mileage figure — or a separator.
    """
    for make in _MAKES_LONGEST_FIRST:
        match = re.search(re.escape(make), text, re.IGNORECASE)
        if not match:
            continue
        remainder = text[match.end():].strip(" |·,-")
        model_match = re.match(
            r"[A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*){0,3}", remainder
        )
        model = model_match.group(0).strip() if model_match else None
        return make, (model or None)
    return None, None


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
    """
    schema.org Car/Vehicle/Product markup, when a listing page carries it.

    Tried before any text guessing, because when it exists it is structured
    data written for exactly this purpose rather than a pattern inferred from
    a title meant for a person to read.
    """
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
    """
    Best-effort make, model, year and stock number for the vehicle a listing
    page is about. None means nothing reliable was found, not that the page
    has no vehicle on it.

    Structured data first (see `_vehicle_details_from_json_ld`) on the pages
    that carry it; most import-site listings do not, so the fallback reads
    the page's own title and description text. Variant/trim is deliberately
    left for the dealer: it is the field a title is least likely to spell out
    unambiguously (is "GT" a trim or the last word of a model name?), and a
    wrong guess there is worse than a blank optional field.
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
    details = VehicleDetails(
        make=make,
        model=model,
        year=_year_from_text(combined),
        stock_number=_stock_number_from_text(combined),
    )
    return None if details.is_empty() else details


def is_large_enough(content: bytes) -> bool:
    """
    True if both sides of the image reach MIN_IMAGE_PIXELS.

    Only the header is read — Image.open is lazy, and the size is known before
    any pixels are decoded, so this costs nothing on a 3 MB photograph.

    Every failure to read is a rejection, and the except is broad on purpose:
    this is a file fetched from a page nobody here controls, and whatever we
    cannot measure is not something to hand to the pipeline. Pillow's own
    failures for such input span UnidentifiedImageError, OSError and
    DecompressionBombError, which share no useful base class.
    """
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
    """
    Fetch a listing page and return whatever `extract_vehicle_details` can
    read from it, without downloading any of its photographs.

    For the moment a URL is first pasted — before a listing exists, and
    before the dealer has necessarily decided to import its gallery at all —
    pre-filling three text fields should not cost the time or bandwidth of
    downloading twenty photographs that a moment later turn out not to be
    wanted, or belong to a listing the dealer decides not to save. Actually
    importing a gallery remains `fetch_images`, run separately and unchanged
    by this function existing.

    Raises UrlImportError for the same host-policy and network failures as
    `fetch_images`, with the same messages. Returns None, not an error, for a
    page that loads fine but is not HTML or yields nothing readable — that is
    a normal outcome here, not a problem to report.
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
    """
    Fetch a listing page and return the vehicle photographs found on it.

    Raises UrlImportError with a message worth showing to the user. Returning
    an empty list is reserved for "the page loaded and genuinely had nothing",
    which the caller reports differently from a refusal.
    """
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
            # The signature of a WAF. Say so, rather than letting the dealer
            # think their own listing is at fault.
            raise UrlImportError(
                "That site blocks automated requests, so its photographs cannot "
                "be imported. Download them and upload them instead."
            )
        if response.status_code >= 400:
            raise UrlImportError(
                f"That page responded with status {response.status_code}."
            )

        # A redirect may have landed somewhere the original host check did not
        # cover, so the final host is re-checked against both policies.
        final_host = urlparse(str(response.url)).hostname
        check_host_policy(final_host)
        if not is_safe_host(final_host):
            raise UrlImportError("That address cannot be reached from the server.")

        content_type = (
            response.headers.get("content-type", "").split(";")[0].strip().lower()
        )

        # The URL is itself an image.
        if content_type in ALLOWED_IMAGE_TYPES:
            entry = _build(str(response.url), response.content, content_type, 0)
            return ImportResult(images=[entry] if entry else [])

        if "html" not in content_type:
            raise UrlImportError(
                "That address is neither a webpage nor an image we can read."
            )

        if len(response.content) > MAX_PAGE_BYTES:
            raise UrlImportError("That page is too large to scan.")

        # Read once, up front, from the same fetch the photographs come from —
        # no extra request. Kept independent of whether any photograph is
        # found below: a page whose gallery is painted in by JavaScript can
        # still carry a perfectly good <title>, and a dealer who gets nothing
        # else out of an import should not also lose the make and model it
        # found for the sake of one failed photograph.
        vehicle = extract_vehicle_details(response.text)

        candidates = extract_image_urls(response.text, base_url=str(response.url))
        if not candidates:
            raise UrlImportError(
                "No photographs were found on that page. Sites that build their "
                "gallery in the browser cannot be imported this way."
            )

        # Over-fetch: some candidates will be logos, icons or dead links.
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
            # Applied to scraped candidates only. A URL that is itself an image
            # was chosen by the person who pasted it, and silently dropping it
            # would leave them with "no photographs found" about a photograph
            # they were looking at.
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
