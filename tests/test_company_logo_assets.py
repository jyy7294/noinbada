from __future__ import annotations

import socket
import struct

import pytest

from trzip import company_logo_assets as logos


PUBLIC_IP = "93.184.216.34"


def _png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"


@pytest.fixture(autouse=True)
def _clean_cache_and_public_dns(monkeypatch):
    logos.clear_company_logo_cache()
    monkeypatch.setattr(
        logos,
        "_resolve_host_addresses",
        lambda _host, _port: {logos.ipaddress.ip_address(PUBLIC_IP)},
    )
    yield
    logos.clear_company_logo_cache()


def test_candidate_priority_prefers_apple_icon_then_icon_logo_and_og(monkeypatch):
    page = b"""<!doctype html><html><head>
      <meta property="og:image" content="https://media.official-cdn.example/social.png">
      <link rel="icon" href="/favicon.png">
      <link rel="apple-touch-icon" href="https://media.official-cdn.example/apple.png">
      </head><body><img class="company-logo" src="/logo.png"></body></html>"""
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        if url == "https://corp.example/":
            return logos._FetchResult(url, 200, "text/html; charset=utf-8", page)
        return logos._FetchResult(url, 200, "image/png", _png(180, 180))

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    result = logos.resolve_company_logo("https://corp.example")

    assert result["status"] == "verified"
    assert result["candidate_kind"] == "apple_touch_icon"
    assert result["asset_url"] == "https://media.official-cdn.example/apple.png"
    assert result["asset_scope"] == "official_page_declared_cdn"
    assert result["width"] == result["height"] == 180
    assert result["sha256"]
    assert calls == ["https://corp.example/", "https://media.official-cdn.example/apple.png"]


def test_low_resolution_raster_is_rejected_and_next_sharp_candidate_wins(monkeypatch):
    page = b"""<html><head>
      <link rel="apple-touch-icon" href="/tiny.png">
      <link rel="icon" href="/sharp.png">
      </head></html>"""

    def fake_fetch(url, **_kwargs):
        if url == "https://corp.example/":
            return logos._FetchResult(url, 200, "text/html", page)
        size = 32 if url.endswith("tiny.png") else 128
        return logos._FetchResult(url, 200, "image/png", _png(size, size))

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    result = logos.resolve_company_logo("https://corp.example/")

    assert result["status"] == "verified"
    assert result["candidate_kind"] == "icon"
    assert result["asset_url"] == "https://corp.example/sharp.png"
    assert result["verification"] == "verified_raster_min_64px"


@pytest.mark.parametrize(
    "unsafe_svg",
    [
        b'<svg viewBox="0 0 100 100"><script>alert(1)</script></svg>',
        b'<svg viewBox="0 0 100 100"><image href="https://evil.example/a.png"/></svg>',
        b'<svg viewBox="0 0 100 100" onload="alert(1)"></svg>',
        b'<svg viewBox="0 0 100 100"><style>@import "https://evil.example/a.css";</style></svg>',
        b'<svg><rect width="100" height="100"/></svg>',
        b'<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><svg viewBox="0 0 100 100"/>',
    ],
)
def test_svg_requires_viewbox_and_rejects_script_or_external_reference(monkeypatch, unsafe_svg):
    page = b'<html><head><link rel="icon" href="/logo.svg"></head></html>'

    def fake_fetch(url, **_kwargs):
        if url == "https://corp.example/":
            return logos._FetchResult(url, 200, "text/html", page)
        return logos._FetchResult(url, 200, "image/svg+xml", unsafe_svg)

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    result = logos.resolve_company_logo("https://corp.example/")

    assert result["status"] == "fallback"
    assert result["verification"] == "initials_fallback"
    assert result["asset_url"] is None


def test_safe_inline_svg_is_verified(monkeypatch):
    page = b'<html><body><img id="brand-logo" src="/logo.svg"></body></html>'
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 80"><defs><linearGradient id="g"/></defs><path fill="url(#g)" d="M0 0h320v80H0z"/></svg>'

    def fake_fetch(url, **_kwargs):
        if url == "https://corp.example/":
            return logos._FetchResult(url, 200, "text/html", page)
        return logos._FetchResult(url, 200, "image/svg+xml; charset=utf-8", svg)

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    result = logos.resolve_company_logo("https://corp.example/")

    assert result["status"] == "verified"
    assert result["verification"] == "verified_safe_svg"
    assert (result["width"], result["height"]) == (320, 80)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/logo",
        "http://127.0.0.1/logo",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.2/logo",
        "https://user:password@corp.example/",
        "https://corp.example:8443/",
    ],
)
def test_ssrf_and_non_http_targets_fail_closed_without_network(monkeypatch, url):
    calls = []
    monkeypatch.setattr(logos, "_http_fetch", lambda *_args, **_kwargs: calls.append(True))

    result = logos.resolve_company_logo(url)

    assert result["status"] == "fallback"
    assert result["verification"] == "initials_fallback"
    assert calls == []


def test_redirect_handler_rejects_private_redirect(monkeypatch):
    request = logos.urllib.request.Request("https://corp.example/")
    handler = logos._PublicOnlyRedirectHandler()

    with pytest.raises(ValueError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/admin",
        )


def test_private_asset_declared_by_public_page_is_never_fetched(monkeypatch):
    page = b'<html><head><link rel="icon" href="http://127.0.0.1/logo.png"></head></html>'
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        return logos._FetchResult(url, 200, "text/html", page)

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    result = logos.resolve_company_logo("https://corp.example/")

    assert result["status"] == "fallback"
    assert calls == ["https://corp.example/"]


def test_timeout_returns_initials_fallback(monkeypatch):
    def timeout(_url, **_kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(logos, "_http_fetch", timeout)
    result = logos.resolve_company_logo("https://corp.example/")

    assert result["status"] == "fallback"
    assert result["reason"] == "homepage_timeout"
    assert result["asset_url"] is None


def test_bounded_cache_reuses_result_and_is_copy_safe(monkeypatch):
    page = b'<html><head><link rel="icon" href="/logo.png"></head></html>'
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        if url == "https://corp.example/":
            return logos._FetchResult(url, 200, "text/html", page)
        return logos._FetchResult(url, 200, "image/png", _png(128, 128))

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    first = logos.resolve_company_logo("https://corp.example", cache_max_entries=1)
    first["asset_url"] = "mutated"
    second = logos.resolve_company_logo("https://corp.example/", cache_max_entries=1)

    assert calls == ["https://corp.example/", "https://corp.example/logo.png"]
    assert second["cache"] == "hit"
    assert second["asset_url"] == "https://corp.example/logo.png"


def test_cache_evicts_oldest_entry_at_configured_bound(monkeypatch):
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        if url.endswith("logo.png"):
            return logos._FetchResult(url, 200, "image/png", _png(128, 128))
        return logos._FetchResult(
            url,
            200,
            "text/html",
            b'<html><head><link rel="icon" href="/logo.png"></head></html>',
        )

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    logos.resolve_company_logo("https://first.example/", cache_max_entries=1)
    logos.resolve_company_logo("https://second.example/", cache_max_entries=1)
    logos.resolve_company_logo("https://first.example/", cache_max_entries=1)

    assert calls.count("https://first.example/") == 2
    assert len(logos._CACHE) == 1


def test_mime_mismatch_and_oversized_fetch_failure_do_not_publish(monkeypatch):
    page = b'<html><head><link rel="icon" href="/not-image.png"></head></html>'

    def fake_fetch(url, **_kwargs):
        if url == "https://corp.example/":
            return logos._FetchResult(url, 200, "text/html", page)
        return logos._FetchResult(url, 200, "text/html", _png(128, 128))

    monkeypatch.setattr(logos, "_http_fetch", fake_fetch)
    result = logos.resolve_company_logo("https://corp.example/")

    assert result["status"] == "fallback"
    assert result["verification"] == "initials_fallback"
