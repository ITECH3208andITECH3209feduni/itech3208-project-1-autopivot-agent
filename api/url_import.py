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
import ipaddress
import logging
import mimetypes
import os
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("autopivot.url_import")

MAX_IMAGES = 20
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_BYTES = 2 * 1024          # skips tracking pixels and spacer gifs
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
class ImportResult:
    images: list[FetchedImage] = field(default_factory=list)
    note: str | None = None


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
            "URL import — host=%s candidates=%d imported=%d",
            parsed.hostname, len(candidates), len(images),
        )
        return ImportResult(images=images, note=note)
