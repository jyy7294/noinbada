from __future__ import annotations

import copy
import hashlib
import http.client
import ipaddress
import re
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
from threading import Lock
from typing import Callable


DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_PAGE_BYTES = 512 * 1024
DEFAULT_MAX_ASSET_BYTES = 4 * 1024 * 1024
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_CACHE_MAX_ENTRIES = 256

_ALLOWED_PAGE_MIME_TYPES = {"text/html", "application/xhtml+xml"}
_ALLOWED_IMAGE_MIME_TYPES = {
    "image/svg+xml",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}
_COMMON_TWO_PART_SUFFIXES = {
    "ac.kr",
    "co.kr",
    "go.kr",
    "ne.kr",
    "or.kr",
    "re.kr",
    "com.au",
    "com.br",
    "com.cn",
    "com.hk",
    "com.sg",
    "com.tw",
    "co.jp",
    "co.uk",
    "org.uk",
}
_LOGO_MARKER = re.compile(r"(?:^|[\s_./-])(logo|logotype|wordmark|brand)(?:$|[\s_./-])", re.I)
_EXTERNAL_CSS_URL = re.compile(r"url\s*\(\s*(['\"]?)(?!#)(.*?)\1\s*\)", re.I)


# Logo files below were taken only from each listed company's official CI page
# (or an asset host declared by that page), then checked for HTTP 200, image
# MIME, dimensions/content safety and SHA-256 on 2026-08-15.  The catalog is a
# fail-closed supplement to the page parser: it handles official sites whose
# TLS/markup prevents reliable discovery, without falling back to a search
# engine favicon or an unrelated third-party logo service.
_REVIEWED_COMPANY_LOGOS = {
    ("CJ ENM", "035760"): {
        "accepted_homepage_hosts": {"cjenm.com", "www.cjenm.com"},
        "source_page_url": "https://www.cjenm.com/",
        "asset_url": "https://web2-cf-image.cjenm.com/public/share/systemmng/site/sitemng/Favicon%20(3).ico",
        "mime": "image/x-icon",
        "width": 196,
        "height": 196,
        "sha256": "563b17e1e18da17c7143eaa2401867fc681105a59197641753d014f677018a7c",
        "verification": "verified_raster_min_64px",
        "asset_scope": "official_page_declared_cdn",
    },
    ("삼성전자", "005930"): {
        "accepted_homepage_hosts": {"samsung.com", "www.samsung.com"},
        "source_page_url": "https://www.samsung.com/sec/",
        "asset_url": "https://images.samsung.com/kdp/_pub/icon-footer-dcxi.jpg",
        "mime": "image/jpeg",
        "width": 783,
        "height": 631,
        "sha256": "c9614e173b7305b050facb7f55518ba6319ac81c41176ab11f2b1b24bb2d5c5a",
        "verification": "verified_raster_min_64px",
        "asset_scope": "official_page_declared_cdn",
    },
    ("월트 디즈니 컴퍼니", "DIS"): {
        "accepted_homepage_hosts": {"thewaltdisneycompany.com", "www.thewaltdisneycompany.com"},
        "source_page_url": "https://thewaltdisneycompany.com/",
        "asset_url": "https://thewaltdisneycompany.com/app/uploads/2026/01/organization-logo.png",
        "mime": "image/png",
        "width": 696,
        "height": 696,
        "sha256": "bfa2fc986e345cdf04c1f2d3948e2afc1b4c3a18a1752efddebbba703086ff18",
        "verification": "verified_raster_min_64px",
        "asset_scope": "same_official_domain",
    },
    ("GS리테일", "007070"): {
        "accepted_homepage_hosts": {"gsretail.com", "www.gsretail.com"},
        "source_page_url": "https://www.gsretail.com/",
        "asset_url": "https://hpimg.gsretail.com/_ui/desktop/common/images/icon/gsretail_114.png",
        "mime": "image/png",
        "width": 114,
        "height": 114,
        "sha256": "2cf5f2620d32a2d891df2e359bffea4b8cbaf6b158702180748f804d91550d4e",
        "verification": "verified_raster_min_64px",
        "asset_scope": "official_page_declared_cdn",
    },
    ("동원산업", "006040"): {
        "accepted_homepage_hosts": {"dongwon.com", "www.dongwon.com"},
        "source_page_url": "https://www.dongwon.com/en",
        "asset_url": "https://www.dongwon.com/asset/image/logo/dongwon_blue.svg",
        "mime": "image/svg+xml",
        "width": 113,
        "height": 47,
        "sha256": "27543d470b20358cb10f476c3d481ede0cd73a45d513660a6e628b9ac6c9d30a",
        "verification": "verified_safe_svg",
        "asset_scope": "same_official_domain",
    },
    ("대상", "001680"): {
        "accepted_homepage_hosts": {
            "daesang.co.kr", "www.daesang.co.kr", "daesang.com", "www.daesang.com",
        },
        "source_page_url": "https://www.daesang.com/kr/company/ci.jsp",
        "asset_url": "https://www.daesang.com/kr/asset/images/sub/company/daesang_ci.png",
        "mime": "image/png",
        "width": 485,
        "height": 126,
        "sha256": "30c5153f1b630715aad3fe32819303cbd0d09bcd6f5234dbc0484f88c01134e9",
        "verification": "verified_raster_min_64px",
        "asset_scope": "same_official_domain",
    },
    ("한성기업", "003680"): {
        "accepted_homepage_hosts": {"hsep.com", "www.hsep.com"},
        "source_page_url": "https://www.hsep.com/CI",
        "asset_url": "https://cdn.imweb.me/thumbnail/20240320/30e5724b26962.jpg",
        "mime": "image/jpeg",
        "width": 1600,
        "height": 671,
        "sha256": "8ad4e280b7efc6b0f2b59f3f617db5ae987337cd36ce42cbc8d2ee00b43ed147",
        "verification": "verified_raster_min_64px",
        "asset_scope": "official_page_declared_cdn",
    },
    ("사조대림", "003960"): {
        "accepted_homepage_hosts": {"dr.sajo.co.kr"},
        "source_page_url": "https://dr.sajo.co.kr/eng/intro/company_ci.asp",
        "asset_url": "https://dr.sajo.co.kr/eng/images/content/intro/txt_ci02.gif",
        "mime": "image/gif",
        "width": 700,
        "height": 209,
        "sha256": "106d07dd82f52085ba6fda1b3e1b81636836b7ba51a0d16fa9afb38f58ef992b",
        "verification": "verified_raster_min_64px",
        "asset_scope": "same_official_domain",
    },
    ("하림", "136480"): {
        "accepted_homepage_hosts": {"harim.com", "www.harim.com"},
        "source_page_url": "https://www.harim.com/main/",
        "asset_url": "https://www.harim.com/main/img/ci.png",
        "mime": "image/png",
        "width": 198,
        "height": 149,
        "sha256": "ff67be9cdeeeff6a1d6b4f17111ed758dcf3b5e9c6950e1a974442237f8267de",
        "verification": "verified_raster_min_64px",
        "asset_scope": "same_official_domain",
    },
    ("마니커에프앤지", "195500"): {
        "accepted_homepage_hosts": {"manikerfng.com", "www.manikerfng.com"},
        "source_page_url": "https://www.manikerfng.com/",
        "asset_url": "https://www.manikerfng.com/ko/images/logo.png",
        "mime": "image/png",
        "width": 201,
        "height": 67,
        "sha256": "eaf91b586ddfeacac505a1b3ff7386a5e0449d996131edfb8fa9e3cbfb43104c",
        "verification": "verified_raster_min_64px",
        "asset_scope": "same_official_domain",
    },
    ("이마트", "139480"): {
        "accepted_homepage_hosts": {
            "company.emart.com", "emartcompany.com", "www.emartcompany.com",
        },
        "source_page_url": "https://company.emart.com/ko/company/ci.do",
        "asset_url": "https://stimg.emart.com/company/ko/images/ab/img_ci_logo.png",
        "mime": "image/png",
        "width": 750,
        "height": 291,
        "sha256": "b7907a820b1547c2cd3eeac581497dff6a12ba15af2797c451388cb72c58c3d4",
        "verification": "verified_raster_min_64px",
        "asset_scope": "same_official_domain",
    },
}

_REVIEWED_LOGO_BY_HOME_HOST = {
    host.casefold(): (identity, asset)
    for identity, asset in _REVIEWED_COMPANY_LOGOS.items()
    for host in asset["accepted_homepage_hosts"]
}


@dataclass(frozen=True)
class _FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes


@dataclass(frozen=True)
class _Candidate:
    priority: int
    order: int
    kind: str
    url: str


_CACHE: "OrderedDict[tuple[str, int, int], tuple[float, dict]]" = OrderedDict()
_CACHE_LOCK = Lock()


def clear_company_logo_cache() -> None:
    """Clear the bounded process cache (mainly useful for controlled tests)."""

    with _CACHE_LOCK:
        _CACHE.clear()


def reviewed_company_homepage(company_name: str, stock_code: str) -> str:
    """Return a catalog source page only for an exact listed-company identity."""

    asset = _REVIEWED_COMPANY_LOGOS.get(
        (str(company_name or "").strip(), str(stock_code or "").strip())
    )
    return str(asset.get("source_page_url") or "") if asset else ""


def resolve_company_logo(
    official_homepage_url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_page_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    cache_max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
) -> dict:
    """Resolve one sharp logo asset declared by an official company homepage.

    The resolver never searches the open web and never manufactures an asset.
    It only inspects logo declarations on the supplied official page.  A
    failure is deliberately represented as an initials fallback so callers do
    not accidentally publish an unverified image.
    """

    if not isinstance(official_homepage_url, str) or not official_homepage_url.strip():
        return _fallback(None, "official_homepage_url_required")
    if timeout_seconds <= 0:
        return _fallback(None, "invalid_timeout")
    if max_page_bytes < 1 or max_asset_bytes < 1:
        return _fallback(None, "invalid_byte_limit")

    try:
        requested_url = _canonical_http_url(official_homepage_url.strip())
        _assert_public_url(requested_url)
    except (TypeError, ValueError, OSError):
        return _fallback(None, "unsafe_or_invalid_homepage_url")

    reviewed = _reviewed_catalog_result(requested_url)
    if reviewed is not None:
        reviewed["cache"] = "reviewed_catalog"
        return reviewed

    cache_key = (requested_url, int(max_page_bytes), int(max_asset_bytes))
    cached = _cache_get(cache_key)
    if cached is not None:
        cached["cache"] = "hit"
        return cached

    try:
        page = _http_fetch(
            requested_url,
            accept="text/html,application/xhtml+xml",
            timeout_seconds=timeout_seconds,
            max_bytes=max_page_bytes,
        )
        source_page_url = _canonical_http_url(page.url)
        _assert_public_url(source_page_url)
        if page.status != 200:
            result = _fallback(source_page_url, "homepage_http_status_not_200")
        elif _normalize_mime(page.content_type) not in _ALLOWED_PAGE_MIME_TYPES:
            result = _fallback(source_page_url, "homepage_mime_not_html")
        else:
            result = _resolve_from_page(
                page,
                timeout_seconds=timeout_seconds,
                max_asset_bytes=max_asset_bytes,
            )
    except (TimeoutError, socket.timeout):
        result = _fallback(requested_url, "homepage_timeout")
    except (urllib.error.URLError, OSError, ValueError, UnicodeError, http.client.HTTPException):
        result = _fallback(requested_url, "homepage_fetch_failed")

    result["cache"] = "miss"
    requested_ttl = max(0, int(cache_ttl_seconds))
    # A transient page or asset failure must not suppress recovery for hours.
    effective_ttl = requested_ttl if result.get("status") == "verified" else min(requested_ttl, 300)
    _cache_put(
        cache_key,
        result,
        ttl_seconds=effective_ttl,
        max_entries=min(DEFAULT_CACHE_MAX_ENTRIES, max(1, int(cache_max_entries))),
    )
    return copy.deepcopy(result)


def _reviewed_catalog_result(requested_url: str) -> dict | None:
    """Resolve a pre-verified official CI asset for an accepted homepage host."""

    requested_host = (urllib.parse.urlsplit(requested_url).hostname or "").casefold()
    catalog_row = _REVIEWED_LOGO_BY_HOME_HOST.get(requested_host)
    if catalog_row is None:
        return None
    identity, asset = catalog_row
    source_page_url = str(asset.get("source_page_url") or "").strip()
    asset_url = str(asset.get("asset_url") or "").strip()
    mime = _normalize_mime(str(asset.get("mime") or ""))
    width = asset.get("width")
    height = asset.get("height")
    sha256 = str(asset.get("sha256") or "").strip().casefold()
    verification = str(asset.get("verification") or "").strip()
    asset_scope = str(asset.get("asset_scope") or "").strip()
    try:
        source_page_url = _canonical_http_url(source_page_url)
        asset_url = _canonical_http_url(asset_url)
    except ValueError:
        return None
    if (
        urllib.parse.urlsplit(source_page_url).scheme != "https"
        or urllib.parse.urlsplit(asset_url).scheme != "https"
        or mime not in _ALLOWED_IMAGE_MIME_TYPES
        or not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or width < 1
        or height < 1
        or (
            verification == "verified_raster_min_64px"
            and (width < 64 or height < 64)
        )
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or verification not in {"verified_safe_svg", "verified_raster_min_64px"}
        or asset_scope not in {"same_official_domain", "official_page_declared_cdn"}
    ):
        return None
    return {
        "status": "verified",
        "source_page_url": source_page_url,
        "asset_url": asset_url,
        "mime": mime,
        "width": width,
        "height": height,
        "sha256": sha256,
        "verification": verification,
        "candidate_kind": "reviewed_official_ci_asset",
        "asset_scope": asset_scope,
        "catalog_identity": {"company": identity[0], "stock_code": identity[1]},
        "verified_at": "2026-08-15T15:00:00+00:00",
    }


def _resolve_from_page(
    page: _FetchResult,
    *,
    timeout_seconds: float,
    max_asset_bytes: int,
) -> dict:
    source_page_url = _canonical_http_url(page.url)
    try:
        html = page.body.decode("utf-8")
    except UnicodeDecodeError:
        html = page.body.decode("utf-8", errors="replace")
    parser = _LogoHTMLParser()
    parser.feed(html)
    parser.close()

    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for candidate in sorted(parser.candidates, key=lambda item: (item.priority, item.order)):
        try:
            asset_url = _canonical_http_url(
                urllib.parse.urljoin(source_page_url, candidate.url)
            )
        except ValueError:
            continue
        if asset_url in seen:
            continue
        seen.add(asset_url)
        candidates.append(
            _Candidate(candidate.priority, candidate.order, candidate.kind, asset_url)
        )

    for candidate in candidates:
        try:
            _assert_public_url(candidate.url)
            asset = _http_fetch(
                candidate.url,
                accept="image/avif,image/webp,image/svg+xml,image/*",
                timeout_seconds=timeout_seconds,
                max_bytes=max_asset_bytes,
            )
            final_asset_url = _canonical_http_url(asset.url)
            _assert_public_url(final_asset_url)
            if asset.status != 200:
                continue
            mime = _normalize_mime(asset.content_type)
            if mime not in _ALLOWED_IMAGE_MIME_TYPES:
                continue
            verified = _verify_asset(asset.body, mime)
            if verified is None:
                continue
            width, height, verification = verified
            return {
                "status": "verified",
                "source_page_url": source_page_url,
                "asset_url": final_asset_url,
                "mime": mime,
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(asset.body).hexdigest(),
                "verification": verification,
                "candidate_kind": candidate.kind,
                "asset_scope": _asset_scope(source_page_url, final_asset_url),
            }
        except (
            TimeoutError,
            socket.timeout,
            urllib.error.URLError,
            OSError,
            ValueError,
            http.client.HTTPException,
        ):
            continue
    return _fallback(source_page_url, "no_verified_official_logo_asset")


class _LogoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[_Candidate] = []
        self._order = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "").strip() for key, value in attrs}
        tag = tag.casefold()
        if tag == "link":
            href = values.get("href", "")
            rel = {part.casefold() for part in values.get("rel", "").split()}
            if href and any(part.startswith("apple-touch-icon") for part in rel):
                self._add(0, "apple_touch_icon", href)
            elif href and "icon" in rel:
                self._add(1, "icon", href)
        elif tag == "img":
            source = values.get("src", "")
            marker = " ".join(
                values.get(key, "")
                for key in ("id", "class", "alt", "title", "aria-label", "itemprop", "src")
            )
            if source and _LOGO_MARKER.search(marker):
                for srcset_url in _srcset_urls(values.get("srcset", "")):
                    self._add(2, "explicit_logo_image", srcset_url)
                self._add(2, "explicit_logo_image", source)
        elif tag == "meta":
            marker = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content", "")
            if marker == "og:image" and content:
                self._add(3, "og_image", content)

    def _add(self, priority: int, kind: str, url: str) -> None:
        self.candidates.append(_Candidate(priority, self._order, kind, url))
        self._order += 1


def _srcset_urls(value: str) -> list[str]:
    parsed: list[tuple[float, int, str]] = []
    for index, item in enumerate(value.split(",")):
        fields = item.strip().split()
        if not fields:
            continue
        score = 1.0
        if len(fields) > 1:
            descriptor = fields[-1].casefold()
            try:
                if descriptor.endswith("w"):
                    score = float(descriptor[:-1])
                elif descriptor.endswith("x"):
                    score = float(descriptor[:-1]) * 1000
            except ValueError:
                score = 1.0
        parsed.append((score, -index, fields[0]))
    return [url for _score, _index, url in sorted(parsed, reverse=True)]


def _verify_asset(data: bytes, mime: str) -> tuple[int, int, str] | None:
    if not data:
        return None
    if mime == "image/svg+xml":
        dimensions = _safe_svg_dimensions(data)
        if dimensions is None:
            return None
        return (*dimensions, "verified_safe_svg")
    dimensions = _raster_dimensions(data, mime)
    if dimensions is None or dimensions[0] < 64 or dimensions[1] < 64:
        return None
    return (*dimensions, "verified_raster_min_64px")


def _safe_svg_dimensions(data: bytes) -> tuple[int, int] | None:
    prefix = data[:4096].lower()
    if b"<!doctype" in prefix or b"<!entity" in prefix:
        return None
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, UnicodeError, ValueError):
        return None
    if _local_name(root.tag) != "svg":
        return None
    view_box = next(
        (value for key, value in root.attrib.items() if _local_name(key).casefold() == "viewbox"),
        "",
    )
    fields = re.split(r"[\s,]+", str(view_box).strip())
    if len(fields) != 4:
        return None
    try:
        _x, _y, width, height = (float(field) for field in fields)
    except ValueError:
        return None
    if not all(value == value and abs(value) != float("inf") for value in (_x, _y, width, height)):
        return None
    if width <= 0 or height <= 0:
        return None
    for element in root.iter():
        name = _local_name(element.tag).casefold()
        if name in {"script", "foreignobject"}:
            return None
        if name == "style":
            style_text = "".join(element.itertext())
            if (
                "@import" in style_text.casefold()
                or _EXTERNAL_CSS_URL.search(style_text)
                or re.search(r"(?:https?:|data:|javascript:|//)", style_text, re.I)
            ):
                return None
        for raw_key, raw_value in element.attrib.items():
            key = _local_name(raw_key).casefold()
            value = str(raw_value).strip()
            if key.startswith("on"):
                return None
            if key in {"href", "src", "data"} and value and not value.startswith("#"):
                return None
            if _EXTERNAL_CSS_URL.search(value):
                return None
            if re.match(r"^(?:https?:|data:|javascript:|//)", value, re.I):
                return None
    return max(1, round(width)), max(1, round(height))


def _local_name(value: object) -> str:
    text = str(value)
    return text.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _raster_dimensions(data: bytes, mime: str) -> tuple[int, int] | None:
    if mime == "image/png":
        if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        return None
    if mime == "image/gif":
        if len(data) >= 10 and data[:6] in {b"GIF87a", b"GIF89a"}:
            return struct.unpack("<HH", data[6:10])
        return None
    if mime == "image/bmp":
        if len(data) >= 26 and data.startswith(b"BM"):
            width, height = struct.unpack("<ii", data[18:26])
            return abs(width), abs(height)
        return None
    if mime in {"image/x-icon", "image/vnd.microsoft.icon"}:
        if len(data) >= 8 and data[:4] == b"\x00\x00\x01\x00":
            return data[6] or 256, data[7] or 256
        return None
    if mime == "image/jpeg":
        return _jpeg_dimensions(data)
    if mime == "image/webp":
        return _webp_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return None
    position = 2
    start_of_frame = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            return None
        marker = data[position]
        position += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[position:position + 2], "big")
        if segment_length < 2 or position + segment_length > len(data):
            return None
        if marker in start_of_frame and segment_length >= 7:
            height = int.from_bytes(data[position + 3:position + 5], "big")
            width = int.from_bytes(data[position + 5:position + 7], "big")
            return width, height
        position += segment_length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        b1, b2, b3, b4 = data[21:25]
        width = 1 + (((b2 & 0x3F) << 8) | b1)
        height = 1 + (((b4 & 0x0F) << 10) | (b3 << 2) | ((b2 & 0xC0) >> 6))
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        marker = data.find(b"\x9d\x01\x2a", 20, 40)
        if marker >= 0 and marker + 7 <= len(data):
            width = int.from_bytes(data[marker + 3:marker + 5], "little") & 0x3FFF
            height = int.from_bytes(data[marker + 5:marker + 7], "little") & 0x3FFF
            return width, height
    return None


def _fallback(source_page_url: str | None, reason: str) -> dict:
    return {
        "status": "fallback",
        "source_page_url": source_page_url,
        "asset_url": None,
        "mime": None,
        "width": None,
        "height": None,
        "sha256": None,
        "verification": "initials_fallback",
        "candidate_kind": None,
        "asset_scope": None,
        "reason": reason,
    }


def _asset_scope(source_page_url: str, asset_url: str) -> str:
    page_host = (urllib.parse.urlsplit(source_page_url).hostname or "").casefold()
    asset_host = (urllib.parse.urlsplit(asset_url).hostname or "").casefold()
    if page_host == asset_host or _registrable_domain(page_host) == _registrable_domain(asset_host):
        return "same_official_domain"
    return "official_page_declared_cdn"


def _registrable_domain(host: str) -> str:
    labels = [label for label in host.rstrip(".").split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    suffix = ".".join(labels[-2:])
    if suffix in _COMMON_TWO_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _canonical_http_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("http(s) URL with a host required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid port") from exc
    if port not in {None, 80, 443}:
        raise ValueError("only standard HTTP ports are allowed")
    host = parsed.hostname.rstrip(".").casefold()
    if not host:
        raise ValueError("host required")
    default_port = (scheme == "http" and port in {None, 80}) or (
        scheme == "https" and port in {None, 443}
    )
    display_host = f"[{host}]" if ":" in host else host
    netloc = display_host if default_port else f"{display_host}:{port}"
    path = parsed.path or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, ""))


def _assert_public_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsafe URL scheme or host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid port") from exc
    if port not in {None, 80, 443}:
        raise ValueError("non-standard port is not allowed")
    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("local hostname is not allowed")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = _resolve_host_addresses(host, port or (443 if parsed.scheme == "https" else 80))
    else:
        addresses = {literal}
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("only globally routable addresses are allowed")


def _resolve_host_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    ):
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        addresses.add(ipaddress.ip_address(sockaddr[0]))
    return addresses


class _PublicOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        safe_url = _canonical_http_url(urllib.parse.urljoin(req.full_url, newurl))
        _assert_public_url(safe_url)
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def _http_fetch(
    url: str,
    *,
    accept: str,
    timeout_seconds: float,
    max_bytes: int,
) -> _FetchResult:
    _assert_public_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "TRZIP-LogoResolver/1.0",
        },
    )
    opener = urllib.request.build_opener(_PublicOnlyRedirectHandler())
    with opener.open(request, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", response.getcode()))
        final_url = _canonical_http_url(response.geturl())
        _assert_public_url(final_url)
        content_length = str(response.headers.get("Content-Length") or "").strip()
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    raise ValueError("response exceeds byte limit")
            except ValueError as exc:
                if "exceeds" in str(exc):
                    raise
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("response exceeds byte limit")
        content_type = str(response.headers.get("Content-Type") or "")
        return _FetchResult(final_url, status, content_type, body)


def _normalize_mime(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().casefold()


def _cache_get(key: tuple[str, int, int]) -> dict | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= now:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return copy.deepcopy(value)


def _cache_put(
    key: tuple[str, int, int],
    value: dict,
    *,
    ttl_seconds: int,
    max_entries: int,
) -> None:
    if ttl_seconds <= 0:
        return
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + ttl_seconds, copy.deepcopy(value))
        _CACHE.move_to_end(key)
        while len(_CACHE) > max_entries:
            _CACHE.popitem(last=False)
