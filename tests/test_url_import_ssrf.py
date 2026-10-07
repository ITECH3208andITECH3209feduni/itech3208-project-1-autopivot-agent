"""BUG 2 — the URL importer's SSRF guard can be bypassed.

The guard checked the pasted URL and the *final* URL after httpx had already
followed every redirect, so:
  (a) intermediate redirect hops to internal addresses were requested;
  (b) a scraped image URL that 302s to an internal address had its final host
      never checked, so the internal response was fetched and stored;
  (c) DNS was resolved separately from httpx's own connection (rebinding);
  (d) the check used blocking socket.getaddrinfo inside async code;
  (e) bodies were read in full before the size caps were applied.

These tests drive an `httpx.MockTransport` and monkeypatch the module's DNS
resolver, so nothing touches the network:

    pytest tests/test_url_import_ssrf.py -v
"""

import asyncio
import io
import os

import httpx
import pytest
from PIL import Image as PilImage

from api import url_import

PUBLIC_IP = "93.184.215.14"


@pytest.fixture
def fake_dns(monkeypatch):
    """Deterministic, offline name resolution keyed by hostname."""
    table = {
        "public.example": [PUBLIC_IP],
        "img.example": [PUBLIC_IP],
        "cdn.example": [PUBLIC_IP],
        "127.0.0.1": ["127.0.0.1"],
        "169.254.169.254": ["169.254.169.254"],
        "10.0.0.5": ["10.0.0.5"],
        "internal.example": ["10.1.2.3"],
        "metadata.example": ["169.254.169.254"],
    }

    async def _resolve(hostname, port=0):
        try:
            return table[hostname]
        except KeyError:
            raise OSError(f"unknown host {hostname!r}")

    monkeypatch.setattr(url_import, "_resolve", _resolve)
    return table


def _jpeg_bytes(size=(300, 300)) -> bytes:
    # Random pixels so the JPEG comfortably clears MIN_IMAGE_BYTES (2 KB).
    image = PilImage.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _run(coro):
    return asyncio.run(coro)


# ── (a) redirect hops to internal addresses ────────────────────────────────────

@pytest.mark.parametrize(
    "internal",
    ["http://127.0.0.1/secret", "http://169.254.169.254/latest/meta-data/",
     "http://10.0.0.5/admin"],
)
def test_redirect_to_internal_is_refused_and_never_requested(fake_dns, internal):
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": internal})
        return httpx.Response(200, content=b"should never get here")

    transport = httpx.MockTransport(handler)
    with pytest.raises(url_import.UrlImportError):
        _run(url_import.fetch_images("http://public.example/listing", transport=transport))

    internal_host = httpx.URL(internal).host
    assert not any(httpx.URL(u).host == internal_host for u in requested), (
        f"a redirect hop to {internal_host} must never be requested"
    )
    assert requested == ["http://public.example/listing"]


# ── (b) a scraped image that redirects internally ──────────────────────────────

def test_scraped_image_that_redirects_internally_is_dropped(fake_dns):
    good_image = _jpeg_bytes()
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host == "public.example":
            html = (
                "<img src='http://img.example/good.jpg'>"
                "<img src='http://cdn.example/poison.jpg'>"
            )
            return httpx.Response(200, headers={"content-type": "text/html"}, content=html)
        if host == "img.example":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=good_image)
        if host == "cdn.example":
            # A public URL that redirects to the metadata service.
            return httpx.Response(302, headers={"location": "http://169.254.169.254/x"})
        return httpx.Response(200, content=b"internal secret")

    transport = httpx.MockTransport(handler)
    result = _run(url_import.fetch_images("http://public.example/listing", transport=transport))

    assert len(result.images) == 1, "only the genuinely public image should import"
    assert not any(httpx.URL(u).host == "169.254.169.254" for u in requested), (
        "the internal redirect target of a scraped image must never be requested"
    )


# ── (e) oversize bodies are cut off, not read in full ──────────────────────────

def test_oversize_page_is_cut_off_without_being_read_fully(fake_dns):
    produced = {"bytes": 0, "chunks": 0}
    total_chunks = 4096  # 4096 * 64 KiB == 256 MiB available if fully drained

    def handler(request):
        async def body():
            for _ in range(total_chunks):
                produced["chunks"] += 1
                produced["bytes"] += 65536
                yield b"<div></div>" + b"x" * (65536 - 11)

        return httpx.Response(200, headers={"content-type": "text/html"}, content=body())

    transport = httpx.MockTransport(handler)
    with pytest.raises(url_import.UrlImportError) as raised:
        _run(url_import.fetch_images("http://public.example/big", transport=transport))

    assert "too large" in str(raised.value).lower()
    assert produced["bytes"] <= url_import.MAX_PAGE_BYTES + 65536, (
        "reading must stop shortly after the cap, not drain the whole body"
    )
    assert produced["chunks"] < total_chunks


# ── (c) DNS rebinding cannot reach a private IP through the transport ──────────

def test_backend_pins_connection_to_a_validated_public_ip(monkeypatch):
    connected: list[str] = []

    class _Inner:
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            connected.append(host)
            return object()

    async def _resolve(hostname, port=0):
        return [PUBLIC_IP]

    monkeypatch.setattr(url_import, "_resolve", _resolve)
    backend = url_import._PublicOnlyBackend(_Inner())
    _run(backend.connect_tcp("public.example", 443))

    assert connected == [PUBLIC_IP], "must connect to the validated IP, not the hostname"


def test_rebinding_resolver_cannot_connect_to_a_private_ip(monkeypatch):
    connected: list[str] = []

    class _Inner:
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            connected.append(host)
            return object()

    async def _resolve(hostname, port=0):
        # The rebinding shape: one public answer alongside a private one.
        return [PUBLIC_IP, "10.0.0.5"]

    monkeypatch.setattr(url_import, "_resolve", _resolve)
    backend = url_import._PublicOnlyBackend(_Inner())

    import httpcore

    with pytest.raises(httpcore.ConnectError):
        _run(backend.connect_tcp("rebind.example", 80))
    assert connected == [], "no connection may be opened when any answer is private"


# ── classifier unit coverage ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("93.184.215.14", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),
        ("100.100.100.200", False),   # CGNAT
        ("0.0.0.0", False),
        ("224.0.0.1", False),          # multicast
        ("::1", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),   # IPv4-mapped loopback
        ("64:ff9b::7f00:1", False),    # NAT64-embedded 127.0.0.1
    ],
)
def test_address_classifier(ip, public):
    assert url_import._address_is_public(ip) is public


# ── happy path still works ──────────────────────────────────────────────────────

def test_direct_image_url_is_imported(fake_dns):
    image = _jpeg_bytes()

    def handler(request):
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image)

    transport = httpx.MockTransport(handler)
    result = _run(url_import.fetch_images("http://img.example/car.jpg", transport=transport))
    assert len(result.images) == 1
    assert result.images[0].content == image
