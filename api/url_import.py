"""Import vehicle photographs from a listing URL.

The fetching, SSRF guard and HTML parsing are Akhanda Bhandari's work, lifted
out of autopivot_backend.py so the light API can use them without importing
torch.

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
import io
import ipaddress
import logging
import mimetypes
import os
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import anyio
import httpcore
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
# Redirects are followed by hand so each hop's host can be checked before the
# request to it is sent; this bounds the chain the way follow_redirects would.
MAX_REDIRECTS = 5

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


# ── Vehicle guess from the URL itself ───────────────────────────────────────
#
# Confirmed by hand against a live 2cheapcars.co.nz listing:
#   .../car/121007/2015-mitsubishi-delica-d2-hatchback
# The numeric id is the site's own, and everything after it is
# year-make-model-variant...-bodytype, hyphen-joined with no marker for where
# one field ends and the next begins. Year and make are reliable — they are
# always the first two tokens. Model is usually the third, but variant and
# body type cannot be told apart from the slug alone (a body type can itself
# be two words, e.g. "people-mover"), so everything past the model is handed
# back as one "variant" string for a person to glance at and trim rather than
# a guess we would get wrong with false confidence.
#
# Matched on the URL's shape — /car/<id>/<slug> — not on a specific hostname,
# so any other dealer site that happens to use the same convention benefits
# too; a URL that does not fit the shape yields no guess rather than a wrong
# one built from an unrelated path.
_CAR_SLUG_RE = re.compile(r"/car/\d+/([a-z0-9.-]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass
class VehicleGuess:
    year: int
    make: str
    model: str
    variant: str | None = None


def guess_vehicle_from_url(url: str) -> VehicleGuess | None:
    """
    Guess year/make/model/variant from a listing URL's own slug.

    Never fetches the page — the guess comes from the URL text alone, so this
    is synchronous and cheap enough to call on every pasted URL, before a
    listing exists to attach anything to.
    """
    match = _CAR_SLUG_RE.search(urlparse(url).path)
    if not match:
        return None

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


@dataclass
class FetchedImage:
    filename: str
    content_type: str
    content: bytes


@dataclass
class ImportResult:
    images: list[FetchedImage] = field(default_factory=list)
    note: str | None = None


# ── Host policy ────────────────────────────────────────────────────────────────

def _address_is_public(raw_ip: str) -> bool:
    """True only for a genuinely public, routable unicast address.

    `is_global` already rejects the private, loopback, link-local, CGNAT,
    TEST-NET and benchmarking ranges on both families; multicast and the
    reserved space — which includes the IPv4-embedding NAT64 well-known prefix
    `64:ff9b::/96` — are excluded on top of it. An IPv4-mapped IPv6 address is
    unwrapped so `::ffff:127.0.0.1` is judged as `127.0.0.1`.
    """
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


async def _resolve(hostname: str, port: int = 0) -> list[str]:
    """Resolve a hostname to its IP strings without blocking the event loop.

    `socket.getaddrinfo` is a blocking call; `anyio.getaddrinfo` runs it on a
    worker thread, so a slow lookup cannot stall every other request the server
    is handling. This is the single resolution point — the per-hop guard and the
    connection backend both go through it, which is what lets a test replace DNS.
    """
    infos = await anyio.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def is_safe_host(hostname: str | None) -> bool:
    """True if the hostname resolves, and every address it resolves to is public.

    SSRF guard, originally Akhanda Bhandari's. Without it a pasted URL is a way
    to make the server fetch its own metadata service or anything else on the
    pod's network. Every resolved address must be public: a name answering with
    both a public and a private address is refused, which is the shape a DNS
    rebinding answer takes.
    """
    if not hostname:
        return False
    try:
        addresses = await _resolve(hostname)
    except (socket.gaierror, OSError):
        return False
    return bool(addresses) and all(_address_is_public(a) for a in addresses)


async def _ensure_public_host(hostname: str | None) -> None:
    """Raise UrlImportError unless the hostname resolves only to public IPs."""
    if not await is_safe_host(hostname):
        raise UrlImportError("That address cannot be reached from the server.")


class _BlockedAddressError(httpcore.ConnectError):
    """Refused a connection because the host resolved to a non-public address."""


class _PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """A network backend that resolves and validates before it connects.

    The per-hop check in `_open` closes the redirect-chain hole, but it resolves
    DNS separately from the socket httpx then opens; between the two, a rebinding
    answer can flip a name from a public address to a private one. This backend
    removes that window: it resolves once, refuses if any answer is non-public,
    and connects to the very address it validated — while the original hostname
    is preserved for TLS/SNI, which httpcore sets from the URL rather than from
    the connect target.
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        try:
            addresses = await _resolve(host, port)
        except (socket.gaierror, OSError) as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        if not addresses or not all(_address_is_public(a) for a in addresses):
            raise _BlockedAddressError(
                f"refusing to connect to non-public host {host!r}"
            )
        return await self._inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("Unix socket connections are not permitted.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _guarded_transport() -> httpx.AsyncHTTPTransport:
    """An httpx transport whose connections are pinned to validated public IPs.

    The pool reads its network backend when it creates each connection, so
    wrapping the backend before the first request routes every connection — the
    initial fetch, every redirect hop and every image download — through the
    validation in `_PublicOnlyBackend`.
    """
    transport = httpx.AsyncHTTPTransport(retries=0)
    transport._pool._network_backend = _PublicOnlyBackend(
        transport._pool._network_backend
    )
    return transport


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

async def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Read a streamed body, stopping the moment it exceeds max_bytes.

    Returns (body, truncated). Nothing past the cap is pulled from the network,
    so an oversized download is abandoned mid-stream rather than read in full
    and only then rejected.
    """
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > max_bytes:
            return bytes(body[:max_bytes]), True
    return bytes(body), False


def _text(headers: httpx.Headers, body: bytes) -> str:
    """Decode a page body to text using httpx's own charset handling."""
    return httpx.Response(200, headers=headers, content=body).text


async def _open(
    client: httpx.AsyncClient,
    url: str,
    *,
    enforce_policy: bool = False,
) -> tuple[httpx.Response, str]:
    """Open a GET, following redirects by hand and validating every hop's host.

    The client is built with follow_redirects=False, so each hop's host is
    checked *before* the request to it is sent: an intermediate redirect to an
    internal address is refused at the hop and never requested. Returns the
    final streamed response — headers available, body not yet read — and its
    URL; the caller must close it.
    """
    current = url
    hops = 0
    while True:
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise UrlImportError("That address cannot be reached from the server.")
        if enforce_policy:
            check_host_policy(parsed.hostname)
        await _ensure_public_host(parsed.hostname)

        response = await client.send(
            client.build_request("GET", current), stream=True
        )
        if response.has_redirect_location:
            await response.aclose()
            hops += 1
            if hops > MAX_REDIRECTS:
                raise UrlImportError("That page redirected too many times.")
            nxt = response.next_request
            current = (
                str(nxt.url)
                if nxt is not None
                else urljoin(current, response.headers.get("location", ""))
            )
            continue
        return response, str(response.url)


async def fetch_images(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ImportResult:
    """
    Fetch a listing page and return the vehicle photographs found on it.

    Raises UrlImportError with a message worth showing to the user. Returning
    an empty list is reserved for "the page loaded and genuinely had nothing",
    which the caller reports differently from a refusal.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise UrlImportError("Enter a full address beginning http:// or https://.")

    # Fast, resolution-free rejection of hosts already known not to work, so the
    # dealer gets the named reason even for a host that would not resolve. Every
    # hop's host is re-checked inside _open (SSRF) as the redirects are followed.
    check_host_policy(parsed.hostname)

    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS,
        timeout=FETCH_TIMEOUT,
        # Followed by hand in _open so each hop's host is validated before the
        # request to it goes out; the ambient proxy env is ignored so a
        # connection lands where it was validated, not at a proxy.
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=CONCURRENT_DOWNLOADS),
        transport=transport or _guarded_transport(),
    ) as client:
        try:
            response, final_url = await _open(client, url, enforce_policy=True)
        except UrlImportError:
            raise
        except httpx.HTTPError as exc:
            logger.info("URL import could not reach %s: %s", parsed.hostname, exc)
            raise UrlImportError("That page could not be reached.") from exc

        try:
            if response.status_code in (401, 403, 429):
                # The signature of a WAF. Say so, rather than letting the dealer
                # think their own listing is at fault.
                raise UrlImportError(
                    "That site blocks automated requests, so its photographs "
                    "cannot be imported. Download them and upload them instead."
                )
            if response.status_code >= 400:
                raise UrlImportError(
                    f"That page responded with status {response.status_code}."
                )

            content_type = (
                response.headers.get("content-type", "").split(";")[0].strip().lower()
            )

            # The URL is itself an image.
            if content_type in ALLOWED_IMAGE_TYPES:
                body, truncated = await _read_capped(response, MAX_IMAGE_BYTES)
                if truncated:
                    raise UrlImportError(
                        f"That image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
                    )
                entry = _build(final_url, body, content_type, 0)
                return ImportResult(images=[entry] if entry else [])

            if "html" not in content_type:
                raise UrlImportError(
                    "That address is neither a webpage nor an image we can read."
                )

            body, truncated = await _read_capped(response, MAX_PAGE_BYTES)
            if truncated:
                raise UrlImportError("That page is too large to scan.")
            html = _text(response.headers, body)
        finally:
            await response.aclose()

        candidates = extract_image_urls(html, base_url=final_url)
        if not candidates:
            raise UrlImportError(
                "No photographs were found on that page. Sites that build their "
                "gallery in the browser cannot be imported this way."
            )

        # Over-fetch: some candidates will be logos, icons or dead links.
        candidates = candidates[: MAX_IMAGES * 2]
        semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

        async def fetch_one(image_url: str, index: int) -> FetchedImage | None:
            async with semaphore:
                try:
                    # _open validates every hop, so a public image URL that
                    # 302s to an internal address is refused at that hop and
                    # dropped — its final host is checked, not just the scraped
                    # one, and the internal address is never requested.
                    reply, _reply_url = await _open(client, image_url)
                except (UrlImportError, httpx.HTTPError):
                    return None
                try:
                    if reply.status_code >= 400:
                        return None
                    ctype = (
                        reply.headers.get("content-type", "")
                        .split(";")[0].strip().lower()
                    )
                    if ctype not in ALLOWED_IMAGE_TYPES:
                        return None
                    body, truncated = await _read_capped(reply, MAX_IMAGE_BYTES)
                finally:
                    await reply.aclose()
            if truncated or not MIN_IMAGE_BYTES <= len(body) <= MAX_IMAGE_BYTES:
                return None
            # is_large_enough is applied to scraped candidates only. A URL that
            # is itself an image was chosen by the person who pasted it, and
            # silently dropping it would leave them with "no photographs found"
            # about a photograph they were looking at.
            if not is_large_enough(body):
                return None
            return _build(image_url, body, ctype, index)

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
            "URL import — host=%s candidates=%d imported=%d",
            parsed.hostname, len(candidates), len(images),
        )
        return ImportResult(images=images, note=note)
