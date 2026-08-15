"""Reviewed publication feed consumed by the MVP frontend.

This feed fixes the ten editorially approved observed events for the current
MVP presentation.  It does not replace or mutate the canonical X/Google
ranking.  Reference enrichment is allowed to improve display detail only.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from .company_logo_assets import resolve_company_logo, reviewed_company_homepage
from .company_roles import select_role_diverse_company_projection, with_company_role
from .editorial_review import KEYWORDS, _verified_company_rows
from .keyword_policy import keyword_fits_public_label, normalized_keyword_text


VERIFIED_AT = "2026-08-14T00:00:00+00:00"
GOOGLE_TRENDS_KR = "https://trends.google.com/trending?geo=KR"
LOGO_MINIMUM_DIMENSION = 64
LOGO_QUALITY_POLICY = "avatar-sharpness-v1"
LOGO_ASSET_VERIFICATION = "static_allowlist_image_quality_2026_08_15"
LIVE_LOGO_ASSET_VERIFICATIONS = frozenset({
    "verified_safe_svg",
    "verified_raster_min_64px",
    "initials_fallback",
})


def _finite_market_number(value: object, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return value > 0 if positive else True


def _public_url(value: object) -> bool:
    return str(value or "").strip().startswith(("http://", "https://"))


def _calculated_roe_provenance_is_valid(value: object) -> bool:
    """Accept only TTM/annual ROE backed by a two-point average equity."""

    if not isinstance(value, dict) or value.get("roe_calculated") is not True:
        return False
    roe_pct = value.get("roe_pct")
    numerator = value.get("roe_numerator")
    denominator = value.get("roe_denominator")
    if (
        not _finite_market_number(roe_pct)
        or not isinstance(numerator, dict)
        or not isinstance(denominator, dict)
    ):
        return False
    numerator_type = numerator.get("type")
    expected_basis = {
        "trailingNetIncome": (
            "trailing_net_income / average_two_point_stockholders_equity * 100"
        ),
        "annualNetIncome": (
            "annual_net_income / average_two_point_stockholders_equity * 100"
        ),
    }.get(numerator_type)
    if not expected_basis or value.get("roe_basis") != expected_basis:
        return False
    numerator_value = numerator.get("value")
    denominator_value = denominator.get("value")
    observations = denominator.get("observations")
    if (
        not _finite_market_number(numerator_value)
        or not _finite_market_number(denominator_value, positive=True)
        or not str(numerator.get("as_of") or "").strip()
        or not str(numerator.get("period_type") or "").strip()
        or denominator.get("type") != "averageStockholdersEquity"
        or denominator.get("period_type") != "TWO_POINT_AVERAGE"
        or not str(denominator.get("period_start") or "").strip()
        or not str(denominator.get("period_end") or "").strip()
        or not isinstance(observations, list)
        or len(observations) != 2
    ):
        return False
    observation_values = []
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or not _finite_market_number(observation.get("value"), positive=True)
            or not str(observation.get("as_of") or "").strip()
        ):
            return False
        observation_values.append(float(observation["value"]))
    if not math.isclose(
        float(denominator_value),
        sum(observation_values) / 2,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return False
    calculated = float(numerator_value) / float(denominator_value) * 100
    return math.isclose(
        float(roe_pct),
        calculated,
        rel_tol=1e-6,
        abs_tol=5e-4,
    )


COMPANY_DOMAINS = {
    "동원산업": "dongwon.com",
    "마니커에프앤지": "manikerfng.com",
    "Canon": "global.canon",
    "Nikon": "nikon.com",
    "Ricoh": "ricoh.com",
    "FUJIFILM Holdings": "fujifilm.com",
    "Sony Group": "sony.com",
    "Adobe": "adobe.com",
    "CJ제일제당": "cj.co.kr",
    "하림": "harim.com",
    "동원F&B": "www.dongwon.com",
    "대상": "daesang.com",
    "풀무원": "pulmuone.co.kr",
    "신세계푸드": "shinsegaefood.com",
    "GS리테일": "gsretail.com",
    "BGF리테일": "cu.bgfretail.com",
    "Atlanta Braves Holdings": "bravesholdings.com",
    "Manchester United plc": "manutd.com",
    "adidas AG": "adidas-group.com",
    "Qualcomm": "qualcomm.com",
    "Comcast Corporation": "corporate.comcast.com",
    "IMAX Corporation": "imax.com",
    "CJ CGV": "cgv.co.kr",
    "HP Inc.": "hp.com",
    "Tesla": "tesla.com",
    "NVIDIA": "nvidia.com",
    "현대자동차": "hyundai.com",
    "UBTECH Robotics": "ubtrobot.com",
    "XPeng": "xpeng.com",
    "레인보우로보틱스": "rainbow-robotics.com",
}

COMPANY_LOGO_ASSETS = {
    "동원산업": {
        "official_domain": "dongwon.com",
        "asset_host": "www.dongwon.com",
        "url": "https://www.dongwon.com/asset/image/logo/dongwon_blue.svg",
        "format": "svg",
        "width": 113,
        "height": 47,
        "render_mode": "image",
    },
    "마니커에프앤지": {
        "official_domain": "manikerfng.com",
        "asset_host": "www.manikerfng.com",
        "url": "https://www.manikerfng.com/ko/images/logo.png",
        "format": "png",
        "width": 201,
        "height": 67,
        "render_mode": "image",
    },
    # Static allowlist of official-site assets (or the asset host referenced by
    # the official page).  HTTP status and image content type were checked once
    # during development; publication validation is intentionally offline.
    "Nikon": {
        "official_domain": "nikon.com",
        "asset_host": "www.nikon.com",
        "url": (
            "https://www.nikon.com/etc.clientlibs/nikoncore/clientlibs/"
            "clientlib-site/resources/img/logo.svg"
        ),
        "format": "svg",
        "width": 68,
        "height": 68,
        "render_mode": "image",
    },
    "Teledyne Technologies": {
        "official_domain": "teledyne.com",
        "asset_host": "cdn.teledyne.com",
        "url": "https://cdn.teledyne.com/assets/common/images/favicon.ico",
        "format": "ico",
        "width": 16,
        "height": 16,
        "render_mode": "initials",
    },
    "Hamamatsu Photonics": {
        "official_domain": "hamamatsu.com",
        "asset_host": "www.hamamatsu.com",
        "url": (
            "https://www.hamamatsu.com/content/dam/hamamatsu-photonics/"
            "system/images/logo.svg"
        ),
        "format": "svg",
        "width": 180,
        "height": 26,
        "render_mode": "image",
    },
    "하림": {
        "official_domain": "harim.com",
        "asset_host": "harim.com",
        "url": "https://harim.com/main/img/ci.png",
        "format": "png",
        "width": 198,
        "height": 149,
        "render_mode": "image",
    },
    "이마트": {
        "official_domain": "company.emart.com",
        "asset_host": "stimg.emart.com",
        "url": "https://stimg.emart.com/company/ko/images/common/sub_logo_company.png",
        "format": "png",
        "width": 53,
        "height": 17,
        "render_mode": "initials",
    },
    "GS리테일": {
        "official_domain": "gsretail.com",
        "asset_host": "hpimg.gsretail.com",
        "url": (
            "https://hpimg.gsretail.com/_ui/desktop/common/images/"
            "icon/gsretail_114.png"
        ),
        "format": "png",
        "width": 114,
        "height": 114,
        "render_mode": "image",
    },
    "롯데관광개발": {
        "official_domain": "company.lottetour.com",
        "asset_host": "company.lottetour.com",
        "url": "https://company.lottetour.com/images/common/header_logo.png",
        "format": "png",
        "width": 89,
        "height": 32,
        "render_mode": "initials",
    },
    "Manchester United plc": {
        "official_domain": "manutd.com",
        "asset_host": "contentfulproxy.stadion.io",
        "url": (
            "https://contentfulproxy.stadion.io/unzgbvss5tuy/"
            "5GFoxbOTd249o0VhuZNczI/cde0cb3a7b895c6a99f2796433232819/"
            "TONAL_CREST_Black%C3%83___3x-png.png?fm=webp&fit=pad&f=center&w=184&h=184"
        ),
        "format": "webp",
        "width": 184,
        "height": 184,
        "render_mode": "image",
    },
    "농심": {
        "official_domain": "nongshim.com",
        "asset_host": "www.nongshim.com",
        "url": "https://www.nongshim.com/resources2/images/common/pop-logo.jpg",
        "format": "jpeg",
        "width": 103,
        "height": 44,
        "render_mode": "initials",
    },
    "롯데웰푸드": {
        "official_domain": "lottewellfood.com",
        "asset_host": "www.lottewellfood.com",
        "url": "https://www.lottewellfood.com/favicon.ico",
        "format": "ico",
        "width": 48,
        "height": 48,
        "render_mode": "initials",
    },
}

COMPANY_LOGO_OVERRIDES = {
    company: str(asset["url"])
    for company, asset in COMPANY_LOGO_ASSETS.items()
}

# Immutable v3 publications created before avatar-sharpness-v1 keep validating
# during audit. New feeds never select these lower-resolution URLs.
LEGACY_COMPANY_LOGO_URLS = {
    "Nikon": "https://www.nikon.com/favicon.ico",
    "Hamamatsu Photonics": (
        "https://www.hamamatsu.com/etc.clientlibs/hpk-global-web/clientlibs/"
        "clientlib-site-resources/resources/favicon.ico"
    ),
    "GS리테일": (
        "https://hpimg.gsretail.com/_ui/desktop/common/images/gsretail/"
        "corporation/logo_gs_en.png"
    ),
}


def logo_asset_contract_is_valid(
    company: str, official_domain: str, logo_url: str,
) -> bool:
    """Validate official logo provenance without making a runtime request."""

    normalized_domain = official_domain.strip().casefold()
    normalized_url = logo_url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    asset = COMPANY_LOGO_ASSETS.get(company)
    if asset is not None:
        accepted_urls = {str(asset["url"])}
        if company in LEGACY_COMPANY_LOGO_URLS:
            accepted_urls.add(LEGACY_COMPANY_LOGO_URLS[company])
        return (
            normalized_domain == str(asset["official_domain"]).casefold()
            and normalized_url in accepted_urls
            and parsed.hostname == str(asset["asset_host"]).casefold()
        )
    expected = (
        "https://www.google.com/s2/favicons?sz=128&domain_url="
        f"https%3A%2F%2F{normalized_domain}"
    )
    return normalized_url == expected


def logo_display_contract_is_valid(company: dict) -> bool:
    """Validate the offline policy that prevents low-resolution avatar upscaling.

    Official vector assets are resolution independent.  Raster assets are
    rendered only when both natural dimensions meet the 64px floor.  Generic
    favicon results have unstable dimensions, so the browser must probe them
    and fall back to initials when the floor is not met.
    """

    if (
        company.get("logo_asset_verification") in LIVE_LOGO_ASSET_VERIFICATIONS
        and isinstance(company.get("logo_provenance"), dict)
    ):
        return live_logo_contract_is_valid(company)

    mode = str(company.get("logo_render_mode") or "")
    asset_format = str(company.get("logo_asset_format") or "").casefold()
    width = company.get("logo_asset_width")
    height = company.get("logo_asset_height")
    minimum = company.get("logo_minimum_dimension")
    runtime_probe = company.get("logo_runtime_probe_required")
    quality = str(company.get("logo_asset_quality") or "")
    if minimum != LOGO_MINIMUM_DIMENSION or not quality:
        return False
    if mode == "image":
        if runtime_probe is not False:
            return False
        asset = COMPANY_LOGO_ASSETS.get(str(company.get("company") or ""))
        if asset is not None and str(company.get("logo_url") or "") != asset["url"]:
            return False
        return asset_format == "svg" or (
            isinstance(width, int)
            and isinstance(height, int)
            and width >= minimum
            and height >= minimum
        )
    if mode == "initials":
        return (
            runtime_probe is False
            and isinstance(width, int)
            and isinstance(height, int)
            and (width < minimum or height < minimum)
            and not str(company.get("logo_url") or "").strip()
            and str(company.get("logo_rejected_asset_url") or "").startswith(
                "https://"
            )
        )
    if mode == "runtime_probe":
        return (
            runtime_probe is True
            and asset_format == "remote_declared_icon"
            and width == 0
            and height == 0
            and company.get("logo_asset_source")
            == "official_domain_declared_favicon"
        )
    return False


def live_logo_contract_is_valid(company: dict) -> bool:
    """Validate a v4 resolver result without consulting the network again."""

    mode = str(company.get("logo_render_mode") or "").strip()
    logo_url = str(company.get("logo_url") or "").strip()
    source_page_url = str(company.get("logo_source_page_url") or "").strip()
    mime = str(company.get("logo_asset_mime") or "").strip().casefold()
    asset_format = str(company.get("logo_asset_format") or "").strip().casefold()
    width = company.get("logo_asset_width")
    height = company.get("logo_asset_height")
    sha256 = str(company.get("logo_asset_sha256") or "").strip().casefold()
    verification = str(company.get("logo_asset_verification") or "").strip()
    provenance = company.get("logo_provenance")
    if (
        company.get("logo_quality_policy") != LOGO_QUALITY_POLICY
        or company.get("logo_minimum_dimension") != LOGO_MINIMUM_DIMENSION
        or company.get("logo_runtime_probe_required") is not False
        or verification not in LIVE_LOGO_ASSET_VERIFICATIONS
        or not isinstance(provenance, dict)
        or provenance.get("source_page_url") != (source_page_url or None)
        or provenance.get("asset_url") != (logo_url or None)
        or provenance.get("mime") != (mime or None)
        or provenance.get("width") != width
        or provenance.get("height") != height
        or provenance.get("sha256") != (sha256 or None)
        or provenance.get("verification") != verification
    ):
        return False

    if mode == "initials":
        return (
            company.get("logo_asset_source") == "initials_fallback"
            and not logo_url
            and not mime
            and asset_format == "none"
            and width == 0
            and height == 0
            and not sha256
            and not str(company.get("logo_asset_host") or "").strip()
            and not str(company.get("logo_rejected_asset_url") or "").strip()
            and (not source_page_url or _http_url_is_valid(source_page_url))
            and str(company.get("logo_asset_quality") or "")
            == "fail_closed_initials_no_verified_asset"
        )

    if mode != "image" or verification not in {
        "verified_safe_svg",
        "verified_raster_min_64px",
    }:
        return False
    parsed_logo = urlparse(logo_url)
    parsed_page = urlparse(source_page_url)
    official_domain = str(company.get("official_domain") or "").strip().casefold()
    dimensions_are_valid = (
        isinstance(width, int)
        and not isinstance(width, bool)
        and isinstance(height, int)
        and not isinstance(height, bool)
        and width > 0
        and height > 0
    )
    if verification == "verified_raster_min_64px":
        dimensions_are_valid = bool(
            dimensions_are_valid
            and width >= LOGO_MINIMUM_DIMENSION
            and height >= LOGO_MINIMUM_DIMENSION
            and asset_format in {"png", "jpeg", "gif", "webp", "bmp", "ico"}
        )
    else:
        dimensions_are_valid = bool(dimensions_are_valid and asset_format == "svg")
    return bool(
        company.get("logo_asset_source") == "official_page_asset"
        and logo_url.startswith("https://")
        and parsed_logo.hostname
        and parsed_page.scheme in {"http", "https"}
        and parsed_page.hostname
        and official_domain == parsed_page.hostname.casefold()
        and str(company.get("logo_asset_host") or "").strip().casefold()
        == parsed_logo.hostname.casefold()
        and mime.startswith("image/")
        and len(sha256) == 64
        and all(character in "0123456789abcdef" for character in sha256)
        and dimensions_are_valid
        and not str(company.get("logo_rejected_asset_url") or "").strip()
        and str(company.get("logo_asset_quality") or "")
        in {"verified_vector", "verified_raster_min_64px"}
    )


def _http_url_is_valid(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


SUPPLEMENT_COMPANY_CATALOG = {
    "sony": ("Sony Group", "6758", "TSE", "sony.com", "영상기기·영화·음악 콘텐츠 사업을 운영하는 일본 상장기업"),
    "adobe": ("Adobe", "ADBE", "NASDAQ", "adobe.com", "영상·이미지 제작 소프트웨어를 제공하는 미국 상장기업"),
    "harim": ("하림", "136480", "KRX", "harim.com", "닭고기 생산·가공과 간편식 사업을 운영하는 국내 상장기업"),
    "dongwon": ("동원F&B", "049770", "KRX", "www.dongwon.com", "가공식품과 가정간편식을 생산·유통하는 국내 상장기업"),
    "daesang": ("대상", "001680", "KRX", "daesang.com", "조미식품·간편식·김치 사업을 운영하는 국내 상장 식품기업"),
    "pulmuone": ("풀무원", "017810", "KRX", "pulmuone.co.kr", "신선식품과 가정간편식을 생산·유통하는 국내 상장기업"),
    "gsretail": ("GS리테일", "007070", "KRX", "gsretail.com", "편의점·슈퍼마켓 등 오프라인 유통망을 운영하는 국내 상장기업"),
    "teledyne": ("Teledyne Technologies", "TDY", "NYSE", "teledyne.com", "과학·산업용 이미징 센서와 카메라를 공급하는 미국 상장 기술기업"),
    "hamamatsu": ("Hamamatsu Photonics", "6965", "TSE", "hamamatsu.com", "광센서와 과학용 검출기를 개발하는 일본 상장 광전자기업"),
    "hoya": ("HOYA", "7741", "TSE", "hoya.com", "광학유리와 필터 소재를 생산하는 일본 상장 광학기업"),
    "gopro": ("GoPro", "GPRO", "NASDAQ", "gopro.com", "야외 촬영용 액션카메라를 개발하는 미국 상장 영상기기기업"),
    "ottogi": ("오뚜기", "007310", "KRX", "ottogi.co.kr", "가정간편식과 국·탕류를 생산하는 국내 상장 식품기업"),
    "sajo": ("사조대림", "003960", "KRX", "sajo.co.kr", "육가공·수산·간편식 제품을 생산·유통하는 국내 상장 식품기업"),
    "maeil": ("매일유업", "267980", "KOSDAQ", "maeil.com", "유제품과 영양식품을 생산하는 국내 상장 식품기업"),
    "emart": ("이마트", "139480", "KRX", "company.emart.com", "대형마트와 식품 리테일 채널을 운영하는 국내 상장 유통기업"),
    "hanwha": ("한화", "000880", "KRX", "hanwha.com", "대형 불꽃행사를 주최하고 연화 기술을 보유한 국내 상장기업"),
    "hotelshilla": ("호텔신라", "008770", "KRX", "shillahotels.com", "호텔·면세·관광 소비 채널을 운영하는 국내 상장기업"),
    "lottetour": ("롯데관광개발", "032350", "KRX", "company.lottetour.com", "여행·관광·복합리조트 사업을 운영하는 국내 상장기업"),
    "koreanair": ("대한항공", "003490", "KRX", "koreanair.com", "국제·국내 항공 여객 서비스를 운영하는 국내 상장 항공사"),
    "kakao": ("카카오", "035720", "KRX", "kakaocorp.com", "지도·모빌리티·콘텐츠 플랫폼을 운영하는 국내 상장 플랫폼기업"),
    "disney": ("The Walt Disney Company", "DIS", "NYSE", "thewaltdisneycompany.com", "ESPN을 포함한 스포츠·미디어 콘텐츠 사업을 운영하는 미국 상장기업"),
    "fox": ("Fox Corporation", "FOXA", "NASDAQ", "foxcorporation.com", "스포츠 중계와 방송 콘텐츠를 운영하는 미국 상장 미디어기업"),
    "apple": ("Apple", "AAPL", "NASDAQ", "apple.com", "디지털 기기와 영상·스포츠 콘텐츠 플랫폼을 운영하는 미국 상장기업"),
    "amazon": ("Amazon", "AMZN", "NASDAQ", "amazon.com", "전자상거래와 Prime Video 스트리밍을 운영하는 미국 상장기업"),
    "tmobile": ("T-Mobile US", "TMUS", "NASDAQ", "t-mobile.com", "미국 이동통신과 스포츠 마케팅을 운영하는 상장 통신기업"),
    "nike": ("Nike", "NKE", "NYSE", "nike.com", "글로벌 스포츠 의류·용품을 개발·판매하는 미국 상장기업"),
    "sportradar": ("Sportradar", "SRAD", "NASDAQ", "sportradar.com", "스포츠 데이터와 미디어 기술을 제공하는 스위스계 미국 상장기업"),
    "genius": ("Genius Sports", "GENI", "NYSE", "geniussports.com", "스포츠 데이터·중계 기술·팬 참여 솔루션을 제공하는 상장기업"),
    "ea": ("Electronic Arts", "EA", "NASDAQ", "ea.com", "스포츠 게임 콘텐츠를 개발·유통하는 미국 상장 게임기업"),
    "dxc": ("DXC Technology", "DXC", "NYSE", "dxc.com", "기업용 IT 운영과 디지털 전환 서비스를 제공하는 미국 상장기업"),
    "marriott": ("Marriott International", "MAR", "NASDAQ", "marriott.com", "글로벌 호텔·여행 멤버십을 운영하는 미국 상장기업"),
    "cocacola": ("Coca-Cola", "KO", "NYSE", "coca-colacompany.com", "글로벌 음료 브랜드와 스포츠 마케팅을 운영하는 미국 상장기업"),
    "amc": ("AMC Entertainment", "AMC", "NYSE", "amctheatres.com", "미국과 유럽에서 멀티플렉스 영화관을 운영하는 상장기업"),
    "cinemark": ("Cinemark", "CNK", "NYSE", "cinemark.com", "미주 지역 멀티플렉스 영화관을 운영하는 미국 상장기업"),
    "dolby": ("Dolby Laboratories", "DLB", "NYSE", "dolby.com", "영화관용 영상·음향 기술을 개발하는 미국 상장기업"),
    "kodak": ("Eastman Kodak", "KODK", "NYSE", "kodak.com", "영화용 필름과 이미징 소재를 생산하는 미국 상장기업"),
    "bmw": ("BMW", "BMW", "XETRA", "bmwgroup.com", "글로벌 자동차 브랜드와 스포츠 파트너십을 운영하는 독일 상장기업"),
    "cisco": ("Cisco", "CSCO", "NASDAQ", "cisco.com", "네트워크·보안·경기장 연결 기술을 제공하는 미국 상장기업"),
    "harmonic": ("Harmonic Drive Systems", "6324", "TSE", "www.hds.co.jp", "정밀 감속기와 로봇 구동부품을 생산하는 일본 상장기업"),
    "nabtesco": ("Nabtesco", "6268", "TSE", "www.nabtesco.com", "산업용 로봇 정밀 감속기를 생산하는 일본 상장기업"),
    "fanuc": ("FANUC", "6954", "TSE", "fanuc.eu", "산업용 로봇과 자동화 장비를 개발하는 일본 상장기업"),
    "samsung": ("삼성전자", "005930", "KRX", "samsung.com", "AI 반도체·센서·로봇 생태계에 투자하는 국내 상장 전자기업"),
    "nongshim": ("농심", "004370", "KRX", "nongshim.com", "라면·스낵·간편식 제품을 생산하는 국내 상장 식품기업"),
    "lottewellfood": ("롯데웰푸드", "280360", "KRX", "lottewellfood.com", "가공식품과 간편식 유통망을 운영하는 국내 상장 식품기업"),
}


REFERENCE_TOP10 = (
    {"display_name": "개기일식", "category": "culture", "category_label": "문화", "sources": ["x", "google_trends"], "reference_score": 80.8439},
    {"display_name": "페르세우스 유성우", "category": "culture", "category_label": "문화", "sources": ["x", "google_trends"], "reference_score": 77.6087},
    {"display_name": "말복·삼계탕", "category": "food", "category_label": "음식", "sources": ["google_trends"], "reference_score": 38.1451},
    {"display_name": "불꽃축제", "category": "culture", "category_label": "문화", "sources": ["x"], "reference_score": 36.1313},
    {"display_name": "메츠 대 브레이브스", "category": "sports", "category_label": "스포츠·야구", "sources": ["google_trends"], "reference_score": 35.6321},
    {"display_name": "맨유 vs 리즈", "canonical_name": "맨체스터 유나이티드 vs 리즈 유나이티드", "category": "sports", "category_label": "스포츠·축구", "sources": ["google_trends"], "reference_score": 34.9404},
    {"display_name": "오디세이 영화", "category": "content", "category_label": "콘텐츠·영화", "sources": ["google_trends"], "reference_score": 33.9079},
    {"display_name": "데포르티보 vs 레알 마드리드", "category": "sports", "category_label": "스포츠·축구", "sources": ["google_trends"], "reference_score": 33.8521},
    {"display_name": "휴머노이드 로봇", "category": "technology", "category_label": "기술", "sources": ["google_trends"], "reference_score": 33.1473},
    {"display_name": "홈플러스 재개장", "category": "consumer", "category_label": "제품·브랜드", "sources": ["google_trends"], "reference_score": 32.7291},
)


PRESENTATION_STAGES = {
    "entry": {"label": "진입", "index": 0},
    "detected": {"label": "포착", "index": 1},
    "spreading": {"label": "확산", "index": 2},
    "mainstream": {"label": "대중화", "index": 3},
}


REFERENCE_DETAILS = {
    "개기일식": {
        "keyword_key": "개기일식",
        "company_key": "천체관측장비",
        "definition": "태양이 달에 완전히 가려지는 천문 현상과 안전 관측 장비에 관심이 집중된 흐름입니다.",
        "why_now": "X와 Google 대한민국 관측에서 일식 시각·경로·관측 장비 검색이 함께 포착됐습니다.",
        "evidence_url": "https://www.usa.canon.com/learning/training-articles/training-articles-list/choosing-a-camera-for-eclipse-photography",
    },
    "페르세우스 유성우": {
        "keyword_key": "페르세우스 유성우",
        "company_key": "유성우천체촬영",
        "definition": "페르세우스자리 방향에서 다수의 유성이 관측되는 계절 천문 이벤트입니다.",
        "why_now": "X와 Google 대한민국 관측에서 극대기·관측 시각·촬영 장비 관심이 함께 포착됐습니다.",
        "evidence_url": "https://nij.nikon.com/cms/sp/p1000_astrophotography/",
    },
    "말복·삼계탕": {
        "keyword_key": "말복",
        "company_key": "말복",
        "definition": "말복을 맞아 삼계탕·보양식·간편식 구매와 외식 관심이 동시에 커진 계절 소비 흐름입니다.",
        "why_now": "Google 대한민국 관측에서 말복과 삼계탕 관련 검색이 같은 사건으로 포착됐습니다.",
        "evidence_url": GOOGLE_TRENDS_KR,
    },
    "불꽃축제": {
        "keyword_key": "불꽃축제",
        "company_key": "불꽃축제",
        "definition": "불꽃 연출을 중심으로 일정·명당·교통·관광 소비가 결합되는 대형 참여형 행사입니다.",
        "why_now": "X 대한민국 관측에서 불꽃축제와 관람 준비 표현이 반복 포착됐습니다.",
        "evidence_url": GOOGLE_TRENDS_KR,
    },
    "메츠 대 브레이브스": {
        "keywords": ("메츠", "브레이브스", "MLB", "선발투수", "경기일정"),
        "definition": "뉴욕 메츠와 애틀랜타 브레이브스의 MLB 맞대결에 경기 일정과 선발 정보 관심이 모인 흐름입니다.",
        "why_now": "Google 대한민국 관측에서 두 구단의 경기 조합 검색이 급증했습니다.",
        "evidence_url": "https://www.bravesholdings.com/about",
    },
    "맨유 vs 리즈": {
        "keywords": ("맨유", "리즈", "프리시즌", "친선경기", "경기일정"),
        "definition": "맨체스터 유나이티드와 리즈 유나이티드의 경기 일정·중계·선수 구성에 관심이 집중된 흐름입니다.",
        "why_now": "Google 대한민국 관측에서 다국어 경기명 검색이 하나의 경기 사건으로 병합됐습니다.",
        "evidence_url": "https://ir.manutd.com/~/media/Files/M/Manutd-IR/documents/2025-mu-plc-form-20-f.pdf",
    },
    "오디세이 영화": {
        "keywords": ("오디세이", "IMAX", "놀란감독", "유니버설", "CGV용산"),
        "definition": "크리스토퍼 놀란의 영화 오디세이가 개봉·IMAX 관람·예매 반응으로 화제가 된 콘텐츠 흐름입니다.",
        "why_now": "Google 대한민국 관측과 개봉 보도에서 작품명·감독·IMAX 관람 수요가 함께 확인됐습니다.",
        "evidence_url": "https://imnews.imbc.com/replay/2026/nwtoday/article/6843061_37012.html",
    },
    "데포르티보 vs 레알 마드리드": {
        "keywords": ("데포르티보", "레알", "친선경기", "경기일정", "축구중계"),
        "definition": "데포르티보와 레알 마드리드의 맞대결을 중심으로 일정·중계 관심이 모인 축구 흐름입니다.",
        "why_now": "Google 대한민국 관측에서 여러 언어의 경기명 검색이 같은 경기 사건으로 병합됐습니다.",
        "evidence_url": "https://www.realmadrid.com/en-US/the-club/sponsors/adidas",
    },
    "휴머노이드 로봇": {
        "keyword_key": "휴머노이드 로봇",
        "company_key": "휴머노이드 로봇",
        "definition": "사람 형태로 이동·조작·작업하는 로봇의 상용화와 핵심부품 생태계에 관심이 커진 기술 흐름입니다.",
        "why_now": "Google 대한민국 관측에서 휴머노이드와 액추에이터·감속기·센서 관심이 함께 포착됐습니다.",
        "evidence_url": GOOGLE_TRENDS_KR,
    },
    "홈플러스 재개장": {
        "keywords": ("홈플러스", "재개장", "재오픈", "대형마트", "매장행사"),
        "definition": "홈플러스 점포의 영업 재개와 식품 중심 매장 재편에 소비자·유통업계 관심이 모인 흐름입니다.",
        "why_now": "Google 대한민국 관측과 보도에서 점포 재개장·온라인 재가동·상품 공급 논의가 확인됐습니다.",
        "evidence_url": "https://www.yna.co.kr/amp/view/AKR20260727135200030",
    },
}


REFERENCE_ALIASES = {
    "말복·삼계탕": ("말복", "삼계탕"),
    "맨유 vs 리즈": ("맨유 vs 리즈", "맨체스터 유나이티드 vs 리즈 유나이티드"),
    "오디세이 영화": ("오디세이", "영화 오디세이", "오디세이 영화"),
    "홈플러스 재개장": ("홈플러스", "홈플러스 재개장"),
}


MANUAL_COMPANIES = {
    "메츠 대 브레이브스": (
        {
            "company": "Atlanta Braves Holdings", "ticker": "BATRA", "market": "NASDAQ",
            "company_description": "애틀랜타 브레이브스 구단과 관련 부동산 자산을 보유한 미국 상장사",
            "company_role_category": "ownership_investment", "relation_type": "ownership",
            "relation_tier": "direct", "reason": "회사 공식 소개가 Atlanta Braves MLB 구단 소유를 명시합니다.",
            "evidence_url": "https://www.bravesholdings.com/about", "matched_keywords": ["브레이브스", "MLB"],
        },
    ),
    "맨유 vs 리즈": (
        {
            "company": "Manchester United plc", "ticker": "MANU", "market": "NYSE",
            "company_description": "맨체스터 유나이티드 축구 구단을 운영하는 미국 상장 법인",
            "company_role_category": "ownership_investment", "relation_type": "ownership",
            "relation_tier": "direct", "reason": "공식 연차보고서가 상장 법인과 맨체스터 유나이티드 구단 운영 관계를 확인합니다.",
            "evidence_url": "https://ir.manutd.com/~/media/Files/M/Manutd-IR/documents/2025-mu-plc-form-20-f.pdf", "matched_keywords": ["맨유"],
        },
        {
            "company": "adidas AG", "ticker": "ADS", "market": "XETRA",
            "company_description": "맨체스터 유나이티드의 공식 유니폼 파트너인 독일 상장 스포츠 기업",
            "company_role_category": "brand_marketing", "relation_type": "brand_collaboration",
            "relation_tier": "value_chain", "reason": "구단 공식 연차보고서가 adidas와의 유니폼 파트너십을 명시합니다.",
            "evidence_url": "https://ir.manutd.com/~/media/Files/M/Manutd-IR/documents/2025-mu-plc-form-20-f.pdf", "matched_keywords": ["맨유"],
        },
        {
            "company": "Qualcomm", "ticker": "QCOM", "market": "NASDAQ",
            "company_description": "Snapdragon 브랜드로 맨체스터 유나이티드를 후원하는 미국 상장 반도체 기업",
            "company_role_category": "brand_marketing", "relation_type": "brand_collaboration",
            "relation_tier": "value_chain", "reason": "구단 공식 연차보고서가 Qualcomm Snapdragon의 전면 유니폼 후원을 명시합니다.",
            "evidence_url": "https://ir.manutd.com/~/media/Files/M/Manutd-IR/documents/2025-mu-plc-form-20-f.pdf", "matched_keywords": ["맨유"],
        },
    ),
    "오디세이 영화": (
        {
            "company": "Comcast Corporation", "ticker": "CMCSA", "market": "NASDAQ",
            "company_description": "Universal Pictures를 보유한 미국 상장 미디어 기업",
            "company_role_category": "ownership_investment", "relation_type": "ownership",
            "relation_tier": "direct", "reason": "Comcast 공식 소개가 Universal Pictures의 제작·배급 사업을 확인합니다.",
            "evidence_url": "https://corporate.comcast.com/company/content-experiences", "matched_keywords": ["오디세이", "유니버설"],
        },
        {
            "company": "IMAX Corporation", "ticker": "IMAX", "market": "NYSE",
            "company_description": "오디세이의 대형 포맷 상영을 제공하는 상장 영화기술 기업",
            "company_role_category": "platform_service", "relation_type": "direct",
            "relation_tier": "direct", "reason": "IMAX 공식 발표가 오디세이의 한국 IMAX 개봉과 글로벌 상영을 확인합니다.",
            "evidence_url": "https://www.imax.com/pr/christopher-nolans-odyssey-continues-its-journey-imax-record", "matched_keywords": ["오디세이", "IMAX"],
        },
        {
            "company": "CJ CGV", "ticker": "079160", "market": "KRX",
            "company_description": "오디세이의 국내 극장·IMAX 관람 수요와 연결되는 상장 영화관 운영사",
            "company_role_category": "retail_sales", "relation_type": "distribution",
            "relation_tier": "direct", "reason": "보도가 CGV 용산아이파크몰의 오디세이 IMAX 좌석 수요를 확인합니다.",
            "evidence_url": "https://www.koreaherald.com/article/10828203", "matched_keywords": ["오디세이", "CGV용산"],
        },
    ),
    "데포르티보 vs 레알 마드리드": (
        {
            "company": "adidas AG", "ticker": "ADS", "market": "XETRA",
            "company_description": "레알 마드리드의 공식 스포츠용품 파트너인 독일 상장 기업",
            "company_role_category": "brand_marketing", "relation_type": "brand_collaboration",
            "relation_tier": "value_chain", "reason": "레알 마드리드 공식 스폰서 페이지가 adidas 파트너십을 확인합니다.",
            "evidence_url": "https://www.realmadrid.com/en-US/the-club/sponsors/adidas", "matched_keywords": ["레알"],
        },
        {
            "company": "HP Inc.", "ticker": "HPQ", "market": "NYSE",
            "company_description": "레알 마드리드의 공식 기술 스폰서인 미국 상장 PC·프린팅 기업",
            "company_role_category": "brand_marketing", "relation_type": "brand_collaboration",
            "relation_tier": "value_chain", "reason": "레알 마드리드 공식 스폰서 페이지가 HP 기술 파트너십을 확인합니다.",
            "evidence_url": "https://www.realmadrid.com/en-US/the-club/sponsors/hp", "matched_keywords": ["레알"],
        },
    ),
    "홈플러스 재개장": (
        {
            "company": "CJ제일제당", "ticker": "097950", "market": "KRX",
            "company_description": "홈플러스의 식품 중심 재개장 과정에서 납품 재개 여부가 보도된 상장 식품기업",
            "company_role_category": "distribution", "relation_type": "distribution",
            "relation_tier": "industry_watch", "reason": "보도가 CJ제일제당이 홈플러스 납품 재개를 검토 중이라고 명시합니다.",
            "evidence_url": "https://www.etnews.com/20260728000237", "matched_keywords": ["홈플러스", "재개장"],
        },
    ),
}


# These rows complete the reviewed MVP cards without changing the canonical
# event score.  Every relation is an explicit listed-company edge and is
# normalized by ``_presentation_company_row`` below.
PRESENTATION_COMPANY_SUPPLEMENTS = {
    "개기일식": (
        ("teledyne", "raw_materials_components", "value_chain", "천체 촬영 카메라에 쓰이는 과학용 이미지 센서·검출기 공급망과 연결됩니다.", ("일식 촬영",)),
        ("hamamatsu", "raw_materials_components", "value_chain", "태양·천체 관측 장비의 광검출 센서 공급망과 연결됩니다.", ("태양 필터",)),
        ("hoya", "raw_materials_components", "industry_watch", "관측용 광학유리와 필터 소재 산업의 비교 기업입니다.", ("일식 안경", "태양 필터", "천체망원경")),
        ("gopro", "brand_marketing", "industry_watch", "야외 일식 촬영과 타임랩스 수요에 노출되는 액션카메라 기업입니다.", ("일식 촬영",)),
    ),
    "페르세우스 유성우": (
        ("teledyne", "raw_materials_components", "value_chain", "저조도 천체 촬영용 과학 이미지 센서 공급망과 연결됩니다.", ("천체 촬영",)),
        ("hamamatsu", "raw_materials_components", "value_chain", "미약한 천체광을 검출하는 광센서 공급망과 연결됩니다.", ("별똥별",)),
        ("hoya", "raw_materials_components", "industry_watch", "천체망원경과 촬영장비의 광학 소재 산업에 연결됩니다.", ("천체망원경",)),
        ("gopro", "brand_marketing", "industry_watch", "유성우 야외 촬영·타임랩스 콘텐츠 수요와 연결됩니다.", ("천체 촬영",)),
    ),
    "말복·삼계탕": (
        ("ottogi", "manufacturing_development", "direct", "복날 국·탕류와 가정간편식 제품을 생산하는 식품 제조사입니다.", ("삼계탕", "보양식")),
        ("sajo", "distribution", "value_chain", "육가공·간편식 생산과 식품 유통망을 통해 복날 소비와 연결됩니다.", ("복날 음식",)),
        ("maeil", "manufacturing_development", "industry_watch", "영양·단백질 식품을 제조하며 보양식 소비의 인접 수요와 연결됩니다.", ("보양식",)),
        ("emart", "retail_sales", "value_chain", "대형마트 식품 매대에서 복날 간편식과 보양식 판매를 담당합니다.", ("간편식 삼계탕",)),
    ),
    "불꽃축제": (
        ("hanwha", "event_sponsorship", "direct", "불꽃축제를 주최하고 연화 연출 기술을 제공하는 직접 행사 운영사입니다.", ("불꽃축제 일정", "불꽃축제 장소")),
        ("hotelshilla", "distribution", "industry_watch", "대형 축제 방문객의 숙박·관광 소비 수요와 연결됩니다.", ("불꽃축제 장소",)),
        ("lottetour", "distribution", "industry_watch", "축제 목적지 관광·여행 상품 수요와 연결됩니다.", ("불꽃축제 티켓",)),
        ("koreanair", "distribution", "industry_watch", "대형 지역행사 방문을 위한 항공 이동 수요와 연결됩니다.", ("불꽃축제 교통",)),
        ("kakao", "platform_service", "value_chain", "축제 장소 검색·교통·모빌리티 안내를 제공하는 플랫폼입니다.", ("불꽃축제 장소", "불꽃축제 교통")),
    ),
    "메츠 대 브레이브스": (
        ("disney", "content_production", "value_chain", "ESPN 스포츠 콘텐츠를 통해 MLB 경기 소비와 연결됩니다.", ("MLB",)),
        ("fox", "content_production", "value_chain", "미국 스포츠 방송과 MLB 경기 콘텐츠 유통에 참여합니다.", ("MLB", "경기일정")),
        ("apple", "platform_service", "value_chain", "디지털 스포츠 중계·구독 플랫폼 수요와 연결됩니다.", ("MLB",)),
        ("amazon", "platform_service", "industry_watch", "스트리밍 스포츠 콘텐츠 시장의 비교 플랫폼입니다.", ("경기일정",)),
        ("tmobile", "brand_marketing", "value_chain", "MLB 팬 대상 통신·브랜드 마케팅 생태계와 연결됩니다.", ("MLB",)),
        ("nike", "brand_marketing", "industry_watch", "프로야구 선수·팬의 스포츠 의류와 용품 소비에 노출됩니다.", ("브레이브스",)),
        ("sportradar", "platform_service", "value_chain", "프로야구 경기 데이터와 미디어 기술을 제공합니다.", ("메츠", "선발투수", "경기일정")),
        ("genius", "platform_service", "value_chain", "스포츠 데이터와 팬 참여 기술 수요에 연결됩니다.", ("선발투수",)),
        ("ea", "content_production", "industry_watch", "프로야구 스포츠 게임·디지털 콘텐츠 시장과 연결됩니다.", ("MLB",)),
    ),
    "맨유 vs 리즈": (
        ("dxc", "platform_service", "value_chain", "프로축구 구단의 IT 운영·디지털 팬 경험 생태계와 연결됩니다.", ("맨유",)),
        ("marriott", "brand_marketing", "industry_watch", "원정 관람객과 스포츠 팬의 여행·숙박 소비에 연결됩니다.", ("친선경기",)),
        ("cocacola", "brand_marketing", "industry_watch", "글로벌 축구 경기의 음료·스포츠 마케팅 수요에 노출됩니다.", ("맨유",)),
        ("ea", "content_production", "value_chain", "축구 구단과 선수를 활용한 스포츠 게임 콘텐츠를 제작합니다.", ("맨유", "리즈")),
        ("fox", "content_production", "industry_watch", "글로벌 축구 중계·스포츠 방송 시장과 연결됩니다.", ("경기일정",)),
        ("genius", "platform_service", "value_chain", "축구 경기 데이터와 팬 참여 솔루션을 제공합니다.", ("프리시즌", "친선경기")),
        ("sportradar", "platform_service", "value_chain", "축구 경기 일정·데이터·미디어 기술을 제공합니다.", ("경기일정",)),
    ),
    "오디세이 영화": (
        ("amc", "retail_sales", "value_chain", "대형 영화 개봉의 북미 극장 관람 수요를 직접 판매합니다.", ("오디세이",)),
        ("cinemark", "retail_sales", "value_chain", "영화 개봉의 극장 상영·관람권 판매 수요와 연결됩니다.", ("오디세이",)),
        ("dolby", "platform_service", "value_chain", "대형 영화의 프리미엄 영상·음향 상영 기술을 공급합니다.", ("IMAX",)),
        ("kodak", "content_production", "value_chain", "대형 포맷 영화 제작에 쓰이는 필름·이미징 소재를 공급합니다.", ("놀란감독",)),
        ("apple", "platform_service", "industry_watch", "극장 개봉 이후 디지털 영화 유통 시장의 비교 플랫폼입니다.", ("오디세이",)),
        ("disney", "content_production", "industry_watch", "글로벌 극장 영화 제작·배급 시장의 비교 상장사입니다.", ("유니버설",)),
        ("sony", "content_production", "industry_watch", "영화 제작·배급과 카메라 기술을 함께 보유한 비교 기업입니다.", ("오디세이",)),
    ),
    "데포르티보 vs 레알 마드리드": (
        ("bmw", "brand_marketing", "value_chain", "레알 마드리드의 모빌리티·브랜드 파트너 생태계와 연결됩니다.", ("레알",)),
        ("cisco", "platform_service", "value_chain", "경기장 네트워크와 스포츠 팬 연결 기술을 제공합니다.", ("레알",)),
        ("adobe", "platform_service", "industry_watch", "구단·스폰서의 디지털 콘텐츠 제작과 팬 마케팅에 연결됩니다.", ("레알",)),
        ("ea", "content_production", "value_chain", "축구 구단과 선수를 활용한 스포츠 게임 콘텐츠를 제작합니다.", ("레알",)),
        ("sportradar", "platform_service", "value_chain", "축구 경기 데이터와 미디어 기술을 제공합니다.", ("데포르티보", "경기일정")),
        ("genius", "platform_service", "value_chain", "축구 데이터와 팬 참여 솔루션을 제공합니다.", ("축구중계",)),
        ("cocacola", "brand_marketing", "industry_watch", "글로벌 축구 경기의 음료·스포츠 마케팅 수요에 연결됩니다.", ("친선경기",)),
        ("fox", "content_production", "industry_watch", "국제 축구 경기의 방송·중계 콘텐츠 시장과 연결됩니다.", ("축구중계",)),
    ),
    "휴머노이드 로봇": (
        ("harmonic", "raw_materials_components", "value_chain", "휴머노이드 관절에 필요한 정밀 감속기 공급망과 연결됩니다.", ("감속기", "액추에이터")),
        ("nabtesco", "raw_materials_components", "value_chain", "산업용 로봇 관절용 정밀 감속기를 공급합니다.", ("감속기",)),
        ("fanuc", "manufacturing_development", "industry_watch", "산업용 로봇·자동화 시스템에서 휴머노이드의 비교 생태계를 형성합니다.", ("로봇",)),
        ("samsung", "ownership_investment", "value_chain", "로봇 기업 투자와 AI 반도체·센서 생태계를 통해 연결됩니다.", ("센서", "휴머노이드")),
    ),
    "홈플러스 재개장": (
        ("harim", "manufacturing_development", "value_chain", "대형마트 식품 매대에 닭고기·간편식 상품을 공급하는 제조사입니다.", ("홈플러스", "재개장")),
        ("dongwon", "distribution", "value_chain", "대형마트에 가공식품을 공급·유통하는 종합식품기업입니다.", ("홈플러스",)),
        ("daesang", "manufacturing_development", "value_chain", "대형마트 식품 매대에 가정간편식과 조미식품을 공급합니다.", ("대형마트",)),
        ("pulmuone", "manufacturing_development", "value_chain", "대형마트에 신선·간편식 제품을 공급하는 상장 식품기업입니다.", ("재오픈",)),
        ("ottogi", "manufacturing_development", "value_chain", "대형마트 식품 매대에 가공식품과 간편식을 공급합니다.", ("대형마트",)),
        ("nongshim", "manufacturing_development", "value_chain", "대형마트 판매 비중이 높은 라면·스낵 공급사입니다.", ("매장행사",)),
        ("lottewellfood", "distribution", "value_chain", "대형마트에 제과·가공식품을 공급·유통합니다.", ("홈플러스",)),
        ("maeil", "raw_materials_components", "value_chain", "대형마트 유제품·영양식 매대의 핵심 공급사입니다.", ("재개장",)),
        ("gsretail", "retail_sales", "industry_watch", "식품 중심 오프라인 리테일 재편을 비교할 수 있는 상장 유통사입니다.", ("대형마트",)),
    ),
}


def _key(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def _stable_float(identity: str, salt: str, low: float, high: float) -> float:
    digest = hashlib.sha256(f"{identity}|{salt}".encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / float((1 << 64) - 1)
    return low + ((high - low) * fraction)


def _market_snapshot(company: str, ticker: str, market: str) -> dict:
    """Return a deterministic display snapshot that never enters ranking."""

    identity = f"{market}:{ticker}:{company}"
    is_kr = market in {"KRX", "KOSPI", "KOSDAQ"}
    is_jp = market == "TSE"
    currency = "KRW" if is_kr else "JPY" if is_jp else "EUR" if market in {"XETRA", "BIT", "EURONEXT_PARIS"} else "USD"
    if is_kr:
        price = _stable_float(identity, "price", 10_000.0, 400_000.0)
    elif is_jp:
        price = _stable_float(identity, "price", 800.0, 7_000.0)
    else:
        price = _stable_float(identity, "price", 10.0, 500.0)
    points = []
    for index in range(30):
        step = _stable_float(identity, f"price-{index}", -0.018, 0.022)
        price = max(price * (1.0 + step), 0.01)
        points.append(round(price, 2))
    change_percent = round(((points[-1] / points[-2]) - 1.0) * 100.0, 2)
    cap_value = _stable_float(identity, "market-cap", 0.8, 80.0)
    if currency == "KRW":
        market_cap_label = f"약 {cap_value:.1f}조원"
        last_price_label = f"{points[-1]:,.0f}원"
    elif currency == "JPY":
        market_cap_label = f"¥{cap_value:.1f}조"
        last_price_label = f"¥{points[-1]:,.0f}"
    elif currency == "EUR":
        market_cap_label = f"€{cap_value:.1f}B"
        last_price_label = f"€{points[-1]:,.2f}"
    else:
        market_cap_label = f"${cap_value:.1f}B"
        last_price_label = f"${points[-1]:,.2f}"
    return {
        "currency": currency,
        "last_price": points[-1],
        "last_price_label": last_price_label,
        "change_percent": change_percent,
        "market_cap_label": market_cap_label,
        "per": round(_stable_float(identity, "per", 7.0, 35.0), 1),
        "pbr": round(_stable_float(identity, "pbr", 0.6, 8.0), 1),
        "roe_percent": round(_stable_float(identity, "roe", 3.0, 30.0), 1),
        "price_series": points,
        "series_period": "30d",
        "as_of": VERIFIED_AT,
        "source_status": "supplemented_display",
        "display_only": True,
        "ranking_effect": "none",
    }


def _catalog_company_source(
    catalog_key: str,
    role_category: str,
    relation_tier: str,
    reason: str,
    matched_keywords: tuple[str, ...],
) -> dict:
    company, ticker, market, domain, description = SUPPLEMENT_COMPANY_CATALOG[catalog_key]
    return {
        "company": company,
        "ticker": ticker,
        "market": market,
        "company_description": description,
        "company_role_category": role_category,
        "relation_type": relation_tier,
        "relation_tier": relation_tier,
        "reason": reason,
        "evidence_url": f"https://{domain}",
        "evidence_owner": company,
        "evidence_type": "official_company_domain_and_reviewed_relationship",
        "official_domain": domain,
        "matched_keywords": list(matched_keywords),
    }


def _normalized_observed_values(candidate: dict, source: str) -> list[float]:
    values = []
    for row in candidate.get("series") or []:
        if str(row.get("source") or "") != source:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if value <= 1.0:
            value *= 100.0
        values.append(round(max(0.0, min(100.0, value)), 2))
    return values


def _display_values(identity: str, source: str, length: int, observed: list[float]) -> list[float]:
    base = _stable_float(identity, f"{source}-{length}-base", 24.0, 52.0)
    lift = _stable_float(identity, f"{source}-{length}-lift", 13.0, 37.0)
    values = []
    for index in range(length):
        ratio = index / max(1, length - 1)
        noise = _stable_float(identity, f"{source}-{length}-{index}", -5.0, 5.0)
        value = base + (lift * ratio) + noise
        values.append(round(max(1.0, min(100.0, value)), 2))
    if observed:
        tail = observed[-min(length, len(observed)):]
        values[-len(tail):] = tail
    return values


def _visualization_series(display_name: str, candidate: dict) -> dict:
    observed_x = _normalized_observed_values(candidate, "x")
    observed_google = _normalized_observed_values(candidate, "google_trends")
    windows = {}
    specs = {
        "1w": (7, ("월", "화", "수", "목", "금", "토", "일")),
        "1m": (30, tuple(f"{index}일" for index in range(1, 31))),
        "3m": (13, tuple(f"{index}주" for index in range(1, 14))),
    }
    for key, (length, labels) in specs.items():
        x_values = _display_values(display_name, f"x-{key}", length, observed_x)
        google_values = _display_values(
            display_name, f"google-{key}", length, observed_google
        )
        combined = [round((x + google) / 2.0, 2) for x, google in zip(x_values, google_values)]
        windows[key] = {
            "labels": list(labels),
            "x": x_values,
            "google_trends": google_values,
            "combined": combined,
            "status": "ready",
            "basis": "observed_plus_deterministic_display_supplement",
            "display_only": True,
            "ranking_effect": "none",
        }
    return {
        "metric": "normalized_attention_index",
        "canonical_series_unchanged": True,
        "display_only": True,
        "ranking_effect": "none",
        **windows,
    }


def _attention_windows(visualization: dict) -> list[dict]:
    rows = []
    for key, label in (("1w", "1주"), ("1m", "1개월"), ("3m", "3개월")):
        values = visualization[key]["combined"]
        head = sum(values[:3]) / 3.0
        tail = sum(values[-3:]) / 3.0
        percent = round(((tail - head) / max(head, 1.0)) * 100.0, 1)
        rows.append({
            "key": key,
            "label": label,
            "metric": "normalized_attention_index_change",
            "status": "supplemented_display",
            "percent": percent,
            "basis": "display_window_first_three_vs_last_three",
            "is_absolute_mention_count": False,
            "display_only": True,
            "ranking_effect": "none",
        })
    return rows


def _keyword_rows(display_name: str, details: dict) -> list[dict]:
    raw = details.get("keywords") or KEYWORDS.get(details.get("keyword_key"), ())
    result = []
    for value in raw:
        text = normalized_keyword_text(value)
        if not keyword_fits_public_label(text) or text in {row["text"] for row in result}:
            continue
        result.append({
            "text": text,
            "status": "reviewed_context_expression",
            "source_status": "researched",
            "source_urls": [details["evidence_url"]],
            "affects_live_rank": False,
        })
        if len(result) == 5:
            break
    if len(result) != 5:
        raise ValueError(f"{display_name}: exactly five short related keywords are required")
    return result


def _manual_company_row(display_name: str, position: int, source: dict) -> dict:
    relation_tier = source["relation_tier"]
    ontology_relation = {
        "direct": "core", "value_chain": "value_chain", "industry_watch": "adjacent",
    }[relation_tier]
    return _presentation_company_row(display_name, position, {
        **source,
        "ontology_relation_tier": ontology_relation,
        "ontology_relation": ontology_relation,
        "industry_node": source["company_role_category"],
        "ontology_path": [display_name, source["company_role_category"], source["company"]],
    })


def _presentation_company_row(display_name: str, position: int, source: dict) -> dict:
    """Normalize every company to one frontend-readable evidence contract."""

    company = str(source.get("company") or "").strip()
    ticker = str(source.get("stock_code") or source.get("ticker") or "").strip()
    market = str(source.get("exchange") or source.get("market") or "").strip()
    description = str(
        source.get("company_description") or source.get("company_summary") or ""
    ).strip()
    reason = str(
        source.get("connection_explanation")
        or source.get("relationship_reason")
        or source.get("reason")
        or ""
    ).strip()
    evidence_url = str(source.get("evidence_url") or "").strip()
    official_domain = str(
        source.get("official_domain") or COMPANY_DOMAINS.get(company) or ""
    ).strip().casefold()
    if not all((company, ticker, market, description, reason)):
        raise ValueError(f"{display_name}: incomplete listed-company identity for {company or 'unknown'}")
    if not evidence_url.startswith(("http://", "https://")):
        raise ValueError(f"{display_name}: public company evidence URL is required for {company}")
    if not official_domain or "." not in official_domain or "/" in official_domain:
        raise ValueError(f"{display_name}: official company domain is required for {company}")
    logo_asset = COMPANY_LOGO_ASSETS.get(company)
    logo_render_mode = (
        str(logo_asset["render_mode"]) if logo_asset else "runtime_probe"
    )
    logo_url = (
        ""
        if logo_render_mode == "initials"
        else COMPANY_LOGO_OVERRIDES.get(
            company,
            # domain_url asks Google's favicon endpoint to resolve the official
            # site's declared icon. The browser still applies the natural-size
            # gate because proxy results can change over time.
            f"https://www.google.com/s2/favicons?sz=128&domain_url=https%3A%2F%2F{official_domain}",
        )
    )
    if logo_url and not logo_asset_contract_is_valid(company, official_domain, logo_url):
        raise ValueError(f"{display_name}: logo asset contract is invalid for {company}")
    logo_asset_format = (
        str(logo_asset["format"]) if logo_asset else "remote_declared_icon"
    )
    logo_asset_width = int(logo_asset["width"]) if logo_asset else 0
    logo_asset_height = int(logo_asset["height"]) if logo_asset else 0

    row = with_company_role({
        **source,
        "ticker": ticker,
        "stock_code": ticker,
        "market": market,
        "exchange": market,
        "company_description": description,
        "company_summary": description,
        "reason": reason,
        "relationship_reason": reason,
        "connection_explanation": reason,
        "evidence_url": evidence_url,
        "evidence_sources": source.get("evidence_sources") or [
            {"url": evidence_url, "source_status": "researched"}
        ],
        "evidence_owner": source.get("evidence_owner") or company,
        "evidence_type": source.get("evidence_type") or "reviewed_public_relationship",
        "official_domain": official_domain,
        "logo_url": logo_url,
        "logo_asset_source": (
            "initials_fallback"
            if logo_render_mode == "initials"
            else "official_page_asset"
            if logo_asset
            else "official_domain_declared_favicon"
        ),
        "logo_asset_host": (
            str(logo_asset["asset_host"])
            if logo_asset else "www.google.com"
        ),
        "logo_asset_verification": LOGO_ASSET_VERIFICATION,
        "logo_quality_policy": LOGO_QUALITY_POLICY,
        "logo_render_mode": logo_render_mode,
        "logo_asset_format": logo_asset_format,
        "logo_asset_width": logo_asset_width,
        "logo_asset_height": logo_asset_height,
        "logo_minimum_dimension": LOGO_MINIMUM_DIMENSION,
        "logo_runtime_probe_required": logo_render_mode == "runtime_probe",
        "logo_asset_quality": (
            "vector"
            if logo_asset_format == "svg"
            else "high_resolution"
            if logo_render_mode == "image"
            else "initials_fallback"
            if logo_render_mode == "initials"
            else "unverified_dimensions_runtime_gate"
        ),
        "logo_rejected_asset_url": (
            str(logo_asset["url"]) if logo_render_mode == "initials" else ""
        ),
        "market_snapshot": _market_snapshot(company, ticker, market),
        "candidate_rank": position,
        "verification_status": "evidence_verified",
        "verified_at": source.get("verified_at") or VERIFIED_AT,
        "review_status": "reviewed_reference",
        "ranking_effect": "none",
        "investment_recommendation": False,
    })
    if not row.get("company_role_public"):
        raise ValueError(f"{display_name}: explicit public company role is required for {company}")
    if not logo_display_contract_is_valid(row):
        raise ValueError(f"{display_name}: logo display contract is invalid for {company}")
    return row


def _company_rows(display_name: str, details: dict) -> list[dict]:
    base_rows = []
    if details.get("company_key"):
        rows = _verified_company_rows(details["company_key"], verified_at=VERIFIED_AT)
        base_rows = [
            _presentation_company_row(display_name, position, row)
            for position, row in enumerate(rows, 1)
            if row.get("company_role_public")
        ]
    else:
        base_rows = [
            _manual_company_row(display_name, position, source)
            for position, source in enumerate(MANUAL_COMPANIES.get(display_name, ()), 1)
        ]
    supplement_sources = [
        _catalog_company_source(*source)
        for source in PRESENTATION_COMPANY_SUPPLEMENTS.get(display_name, ())
    ]
    rows = list(base_rows)
    identities = {(row["exchange"], row["stock_code"]) for row in rows}
    for source in supplement_sources:
        identity = (source["market"], source["ticker"])
        if identity in identities:
            continue
        rows.append(_manual_company_row(display_name, len(rows) + 1, source))
        identities.add(identity)
        if len(rows) == 10:
            break
    if len(rows) != 10:
        raise ValueError(f"{display_name}: exactly ten listed companies are required")
    return rows


def _reference_card(reference: dict, candidates: list[dict]) -> dict:
    display_name = reference["display_name"]
    details = REFERENCE_DETAILS[display_name]
    aliases = REFERENCE_ALIASES.get(display_name, (display_name,))
    alias_keys = {_key(value) for value in aliases}
    candidate = next((
        item for item in candidates
        if alias_keys & {
            _key(item.get("event_key")),
            _key(item.get("display_name")),
            _key(item.get("canonical_topic")),
        }
    ), None)
    story = (candidate or {}).get("trend_story") or {}
    diffusion = story.get("diffusion") or {}
    keywords = _keyword_rows(display_name, details)
    companies = _company_rows(display_name, details)
    visualization = _visualization_series(display_name, candidate or {})
    attention_windows = _attention_windows(visualization)
    one_week_lift = attention_windows[0]["percent"]
    source_badge = " + ".join("Google" if value == "google_trends" else "X" for value in reference["sources"])
    keyword_company_links = [
        {
            "keyword": keyword,
            "company": company["company"],
            "stock_code": company.get("ticker"),
            "company_role_category": company.get("company_role_category"),
            "company_role_label": company.get("company_role_label"),
            "connection_explanation": company.get("connection_explanation") or company.get("reason"),
            "evidence_urls": [company.get("evidence_url")],
        }
        for company in companies
        for keyword in company.get("matched_keywords", [])
        if keyword in {row["text"] for row in keywords}
    ]
    return {
        **reference,
        "topic": (candidate or {}).get("topic") or reference.get("canonical_name") or display_name,
        "event_key": (candidate or {}).get("event_key") or reference.get("canonical_name") or display_name,
        "selection_origin": "reviewed_observed_reference_2026_08_14",
        "data_mode": "observed_reference",
        "currently_observed": bool((candidate or {}).get("is_current")),
        "detail_status": "live_detail" if candidate else "reference_enriched_detail",
        "trend_definition": details["definition"],
        "phenomenon_summary": details["definition"],
        "why_now": details["why_now"],
        "evidence_urls": [details["evidence_url"]],
        "source_badge": source_badge,
        "latest_source_ranks": (candidate or {}).get("latest_source_ranks") or {},
        "lifecycle": (candidate or {}).get("lifecycle") or "new",
        "lifecycle_reason": (candidate or {}).get("lifecycle_reason") or "검수된 당일 관측 사건",
        "trend_stage": diffusion.get("trend_stage") or {
            "key": "detected", "label": "포착", "index": 1,
        },
        "observed_day_label": (
            diffusion.get("observed_day_label")
            or ((candidate or {}).get("frontend_projection") or {}).get("observed_day_label")
            or f"진입 {1 + int(_stable_float(display_name, 'observed-day', 0, 6))}일차"
        ),
        "attention_lift": {
            "status": "supplemented_display",
            "metric": "normalized_attention_index_change",
            "value": one_week_lift,
            "unit": "percent",
            "label": f"최근 1주 {one_week_lift:+.1f}%",
            "basis": "display_window_first_three_vs_last_three",
            "display_only": True,
            "ranking_effect": "none",
        },
        "attention_windows": attention_windows,
        "visualization_series": visualization,
        "series_metric": {
            "key": "normalized_attention_index",
            "label": "언급량 추이 · 관심지수",
            "is_absolute_mention_count": False,
        },
        "keywords": keywords,
        "keyword_status": "ready",
        "companies": companies,
        "company_eligible": bool(companies),
        "company_card_status": "ready" if len(companies) >= 10 else "enrichment_pending",
        "company_card_reason": "evidence_backed_ten_or_more" if len(companies) >= 10 else "verified_companies_below_ten",
        "frontend_readiness_status": "ready" if len(companies) >= 10 else "enrichment_pending",
        "keyword_company_links": keyword_company_links,
        "ranking_effect": "none",
        "score": reference["reference_score"],
        "score_components": (candidate or {}).get("score_components") or {},
        "canonical_series_status": "preserved_unmodified",
        "series": (candidate or {}).get("series") or [],
    }


def _presentation_identity(item: dict) -> tuple[str, ...]:
    """Return stable identifiers used only for publication-to-publication movement."""

    return tuple(
        key
        for key in {
            _key(item.get("event_key")),
            _key(item.get("display_name")),
            _key(item.get("topic")),
        }
        if key
    )


def _presentation_movement(
    item: dict,
    current_position: int,
    previous_items: list[dict],
) -> dict:
    current_identity = set(_presentation_identity(item))
    previous = next(
        (
            row
            for row in previous_items
            if current_identity & set(_presentation_identity(row))
        ),
        None,
    )
    previous_position = None
    if previous is not None:
        raw_position = previous.get("presentation_position") or previous.get("current_rank")
        if isinstance(raw_position, int) and 1 <= raw_position <= 10:
            previous_position = raw_position
    if previous_position is None:
        return {
            "current_rank": current_position,
            "previous_rank": None,
            "delta": None,
            "status": "new",
            "label": "NEW",
            "basis": "previous_published_presentation_feed",
        }
    delta = previous_position - current_position
    if delta > 0:
        status, label = "up", f"▲{delta}"
    elif delta < 0:
        status, label = "down", f"▼{abs(delta)}"
    else:
        status, label = "unchanged", "유지"
    return {
        "current_rank": current_position,
        "previous_rank": previous_position,
        "delta": delta,
        "status": status,
        "label": label,
        "basis": "previous_published_presentation_feed",
    }


def build_reference_demo_feed(
    intelligence: dict, *, previous_feed: dict | None = None
) -> dict:
    """Build the historical reviewed fixture for tests and demo portfolios only.

    This function is deliberately not used by the production publication path.
    Its deterministic display supplements are retained solely so the archived
    design fixture remains reproducible.
    """

    candidates = list(intelligence.get("unified_ranking") or [])
    items = [_reference_card(item, candidates) for item in REFERENCE_TOP10]
    previous_items = list((previous_feed or {}).get("items") or [])
    for position, item in enumerate(items, 1):
        item["presentation_position"] = position
        item["presentation_rank"] = position
        item["current_rank"] = position
        item["rank_movement"] = _presentation_movement(item, position, previous_items)
    return {
        "schema_version": "trzip-presentation-feed-v3",
        "status": "ready",
        "frontend_default": True,
        "logo_policy": {
            "version": LOGO_QUALITY_POLICY,
            "avatar_size_px": 44,
            "minimum_raster_dimension_px": LOGO_MINIMUM_DIMENSION,
            "vector_assets_allowed": True,
            "low_resolution_fallback": "initials",
            "runtime_probe_for_generic_favicons": True,
        },
        "items": items,
        "transition": {
            "enabled": False,
            "policy": "reference_demo_fixture_only",
            "required_clean_hours": 24,
            "synthetic_data_used": True,
            "supplemental_display_data_used": True,
            "canonical_ranking_affected": False,
        },
    }


def _parse_observed_at(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "")).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _observed_sparse_series(candidate: dict, observed_at: datetime) -> dict:
    """Return only actual X/Google observations; never interpolate or pad."""

    rows_by_at: dict[str, dict[str, float]] = defaultdict(dict)
    for row in candidate.get("series") or []:
        source = str(row.get("source") or "")
        stamp = _parse_observed_at(row.get("at"))
        if source not in {"x", "google_trends"} or stamp is None:
            continue
        if row.get("provenance") != "observed" or stamp > observed_at:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        rows_by_at[stamp.isoformat()][source] = round(max(0.0, min(100.0, value)), 2)

    windows = {}
    attention = []
    for key, label, days in (("1w", "1주", 7), ("1m", "1개월", 30), ("3m", "3개월", 90)):
        threshold = observed_at - timedelta(days=days)
        points = []
        for stamp, sources in sorted(rows_by_at.items()):
            parsed = _parse_observed_at(stamp)
            if parsed is None or parsed < threshold:
                continue
            values = list(sources.values())
            points.append({
                "at": stamp,
                "x": sources.get("x"),
                "google_trends": sources.get("google_trends"),
                "combined": round(sum(values) / len(values), 2),
                "observed_sources": sorted(sources),
            })
        combined = [point["combined"] for point in points]
        percent = None
        if len(combined) >= 2 and combined[0] != 0:
            percent = round(((combined[-1] - combined[0]) / combined[0]) * 100.0, 1)
        status = "measured" if len(combined) >= 2 else "insufficient_observed_history"
        windows[key] = {
            "status": status,
            "points": points,
            "available_point_count": len(points),
            "available_from": points[0]["at"] if points else None,
            "available_to": points[-1]["at"] if points else None,
            "basis": "observed_x_google_hourly_points_only",
            "interpolation": "none",
            "missing_point_policy": "preserve_sparse_null_no_reuse",
            "ranking_effect": "none",
        }
        attention.append({
            "key": key,
            "label": label,
            "metric": "normalized_attention_index_change",
            "status": status,
            "percent": percent,
            "basis": "first_and_last_available_observed_point",
            "is_absolute_mention_count": False,
            "ranking_effect": "none",
        })
    return {
        "metric": "normalized_attention_index",
        "canonical_series_unchanged": True,
        "data_mode": "observed_sparse",
        "interpolation": "none",
        "ranking_effect": "none",
        "attention_windows": attention,
        **windows,
    }


def _actual_market_snapshot(company: dict, candidate: dict) -> dict | None:
    market = company.get("market_reference")
    if not isinstance(market, dict):
        code = str(company.get("stock_code") or company.get("ticker") or "")
        market = next((
            row.get("market_reference")
            for row in candidate.get("company_candidates") or []
            if str(row.get("stock_code") or row.get("ticker") or "") == code
            and isinstance(row.get("market_reference"), dict)
        ), None)
    if not isinstance(market, dict) or market.get("status") != "observed":
        return None
    summary = market.get("summary") or {}
    as_of = str(summary.get("as_of") or "").strip()
    provider = str(market.get("provider") or "").strip()
    source_url = str(market.get("source_url") or "").strip()
    if not provider or not as_of or not _public_url(source_url):
        return None
    daily = [
        row for row in market.get("daily_ohlcv") or []
        if isinstance(row, dict)
        and _finite_market_number(row.get("close"), positive=True)
    ]
    if len(daily) != 30:
        # A market chart is public only when the provider supplied every one of
        # the 30 observed sessions.  Never interpolate, repeat, or expose a
        # partial series as if it were complete.
        return None
    dates = [str(row.get("date") or "").strip() for row in daily]
    if not all(dates) or len(set(dates)) != 30 or dates != sorted(dates):
        # Reject duplicated or re-ordered cache rows; the public chart is a
        # chronological sequence of 30 distinct observed trading sessions.
        return None
    valuation = market.get("valuation") or {}
    currency = str(summary.get("currency") or market.get("currency") or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        return None
    fx_reference = market.get("fx_reference") if isinstance(market.get("fx_reference"), dict) else {}
    fx_rate = fx_reference.get("rate")
    fx_as_of = str(fx_reference.get("as_of") or "").strip()
    fx_source_url = str(fx_reference.get("source_url") or "").strip()
    source_urls = market.get("source_urls") if isinstance(market.get("source_urls"), dict) else {}
    field_sources = market.get("field_sources") if isinstance(market.get("field_sources"), dict) else {}
    price_source_url = str(
        field_sources.get("price_series") or source_urls.get("price") or source_url
    ).strip()
    market_cap_source_url = str(
        field_sources.get("market_cap_krw")
        or field_sources.get("market_cap")
        or source_urls.get("fundamentals")
        or source_url
    ).strip()
    market_cap_krw = summary.get("market_cap_krw")
    close_krw = summary.get("close_krw")
    native_market_cap = summary.get("market_cap")
    has_krw_conversion = bool(
        _finite_market_number(market_cap_krw, positive=True)
        and _finite_market_number(native_market_cap, positive=True)
        and _finite_market_number(fx_rate, positive=True)
        and fx_as_of
        and str(fx_reference.get("provider") or "").strip()
        and _public_url(fx_source_url)
        and _public_url(market_cap_source_url)
    )
    snapshot = {
        "status": "observed",
        "provider": provider,
        "source": provider,
        "source_url": source_url,
        "price_source_url": price_source_url,
        "as_of": as_of,
        "last_price": (
            summary.get("close")
            if _finite_market_number(summary.get("close"), positive=True)
            else None
        ),
        "last_price_krw": (
            close_krw
            if has_krw_conversion and _finite_market_number(close_krw, positive=True)
            else None
        ),
        "change_percent": (
            summary.get("daily_change_pct")
            if _finite_market_number(summary.get("daily_change_pct"))
            else None
        ),
        "volume": (
            summary.get("volume")
            if _finite_market_number(summary.get("volume"))
            and summary.get("volume") >= 0
            else None
        ),
        # Public market_cap is always KRW.  The source-currency amount is kept
        # separately for audit and must never be rendered with a won label.
        "market_cap": market_cap_krw if has_krw_conversion else None,
        "market_cap_krw": market_cap_krw if has_krw_conversion else None,
        "market_cap_currency": "KRW" if has_krw_conversion else None,
        "market_cap_source_url": market_cap_source_url if has_krw_conversion else None,
        "native_market_cap": native_market_cap if has_krw_conversion else None,
        "currency": currency,
        "fx_rate_to_krw": fx_rate if has_krw_conversion else None,
        "fx_as_of": fx_as_of if has_krw_conversion else None,
        "fx_provider": str(fx_reference.get("provider") or "") if has_krw_conversion else None,
        "fx_source_url": fx_source_url if has_krw_conversion else None,
        "price_series": [row["close"] for row in daily],
        "price_points": daily,
        "display_only": True,
        "ranking_effect": "none",
    }
    fundamentals_source_url = str(source_urls.get("fundamentals") or source_url).strip()
    for source_key in ("per", "pbr"):
        value = valuation.get(source_key)
        metric_source_url = str(
            field_sources.get(source_key) or fundamentals_source_url
        ).strip()
        if _finite_market_number(value, positive=True) and _public_url(metric_source_url):
            snapshot[source_key] = value
            snapshot[f"{source_key}_source_url"] = metric_source_url
            for suffix in ("as_of", "type", "period_type"):
                provenance = valuation.get(f"{source_key}_{suffix}")
                if provenance not in (None, ""):
                    snapshot[f"{source_key}_{suffix}"] = provenance

    roe_source_url = str(
        field_sources.get("roe_pct") or fundamentals_source_url
    ).strip()
    if _public_url(roe_source_url) and _calculated_roe_provenance_is_valid(valuation):
        value = valuation["roe_pct"]
        snapshot.update({
            "roe_pct": value,
            "roe": value,
            "roe_percent": value,
            "roe_source_url": roe_source_url,
            "roe_basis": valuation["roe_basis"],
            "roe_calculated": True,
            "roe_numerator": valuation["roe_numerator"],
            "roe_denominator": valuation["roe_denominator"],
        })
    return snapshot


def _live_logo_fields(homepage: str) -> dict:
    """Project one verified resolver result into the v4 company DTO."""

    result = resolve_company_logo(homepage) if homepage else {
        "status": "fallback",
        "source_page_url": None,
        "asset_url": None,
        "mime": None,
        "width": None,
        "height": None,
        "sha256": None,
        "verification": "initials_fallback",
    }
    source_page_url = str(result.get("source_page_url") or "").strip()
    asset_url = str(result.get("asset_url") or "").strip()
    mime = str(result.get("mime") or "").split(";", 1)[0].strip().casefold()
    verification = str(result.get("verification") or "initials_fallback").strip()
    width = result.get("width")
    height = result.get("height")
    sha256 = str(result.get("sha256") or "").strip().casefold()
    dimensions_present = bool(
        isinstance(width, int)
        and not isinstance(width, bool)
        and isinstance(height, int)
        and not isinstance(height, bool)
        and width > 0
        and height > 0
    )
    verified = bool(
        result.get("status") == "verified"
        and verification in {"verified_safe_svg", "verified_raster_min_64px"}
        and asset_url.startswith("https://")
        and source_page_url.startswith(("http://", "https://"))
        and mime.startswith("image/")
        and dimensions_present
        and len(sha256) == 64
        and all(character in "0123456789abcdef" for character in sha256)
    )
    if verified:
        format_by_mime = {
            "image/svg+xml": "svg",
            "image/png": "png",
            "image/jpeg": "jpeg",
            "image/gif": "gif",
            "image/webp": "webp",
            "image/bmp": "bmp",
            "image/x-icon": "ico",
            "image/vnd.microsoft.icon": "ico",
        }
        asset_format = format_by_mime.get(mime, "")
        parsed_asset = urlparse(asset_url)
        parsed_page = urlparse(source_page_url)
        verified = bool(asset_format and parsed_asset.hostname and parsed_page.hostname)
    if not verified:
        source_page_url = source_page_url if _http_url_is_valid(source_page_url) else ""
        fields = {
            "official_domain": (
                urlparse(source_page_url).hostname.casefold()
                if source_page_url and urlparse(source_page_url).hostname
                else None
            ),
            "logo_url": "",
            "logo_render_mode": "initials",
            "logo_asset_source": "initials_fallback",
            "logo_asset_host": "",
            "logo_asset_verification": "initials_fallback",
            "logo_asset_format": "none",
            "logo_asset_mime": "",
            "logo_asset_width": 0,
            "logo_asset_height": 0,
            "logo_asset_sha256": "",
            "logo_source_page_url": source_page_url,
            "logo_minimum_dimension": LOGO_MINIMUM_DIMENSION,
            "logo_runtime_probe_required": False,
            "logo_asset_quality": "fail_closed_initials_no_verified_asset",
            "logo_rejected_asset_url": "",
            "logo_quality_policy": LOGO_QUALITY_POLICY,
        }
    else:
        fields = {
            "official_domain": urlparse(source_page_url).hostname.casefold(),
            "logo_url": asset_url,
            "logo_render_mode": "image",
            "logo_asset_source": "official_page_asset",
            "logo_asset_host": urlparse(asset_url).hostname.casefold(),
            "logo_asset_verification": verification,
            "logo_asset_format": asset_format,
            "logo_asset_mime": mime,
            "logo_asset_width": int(width),
            "logo_asset_height": int(height),
            "logo_asset_sha256": sha256,
            "logo_source_page_url": source_page_url,
            "logo_minimum_dimension": LOGO_MINIMUM_DIMENSION,
            "logo_runtime_probe_required": False,
            "logo_asset_quality": (
                "verified_vector"
                if verification == "verified_safe_svg"
                else "verified_raster_min_64px"
            ),
            "logo_rejected_asset_url": "",
            "logo_quality_policy": LOGO_QUALITY_POLICY,
        }
    fields["logo_provenance"] = {
        "source_page_url": fields["logo_source_page_url"] or None,
        "asset_url": fields["logo_url"] or None,
        "mime": fields["logo_asset_mime"] or None,
        "width": fields["logo_asset_width"],
        "height": fields["logo_asset_height"],
        "sha256": fields["logo_asset_sha256"] or None,
        "verification": fields["logo_asset_verification"],
        "candidate_kind": result.get("candidate_kind"),
        "asset_scope": result.get("asset_scope"),
        "verified_at": result.get("verified_at"),
    }
    return fields


def _live_company_rows(candidate: dict) -> list[dict]:
    rows = []
    seen = set()
    for source in candidate.get("companies") or []:
        identity = (
            str(source.get("market") or source.get("exchange") or "").strip(),
            str(source.get("stock_code") or source.get("ticker") or "").strip(),
        )
        if not all(identity) or identity in seen:
            continue
        company = str(source.get("company") or "").strip()
        official = source.get("official_identity") or {}
        homepage = str(official.get("homepage") or "").strip()
        parsed_homepage = urlparse(homepage)
        if (
            parsed_homepage.scheme not in {"http", "https"}
            or not parsed_homepage.hostname
            or "." not in parsed_homepage.hostname
        ):
            homepage = reviewed_company_homepage(company, identity[1])
        logo_fields = _live_logo_fields(homepage)
        evidence_sources = [
            row for row in source.get("evidence_sources") or []
            if str(row.get("url") or "").startswith(("http://", "https://"))
        ]
        evidence_url = str(source.get("evidence_url") or "").strip()
        if not evidence_url and evidence_sources:
            evidence_url = str(evidence_sources[0]["url"])
        if (
            source.get("ontology_complete") is not True
            or not isinstance(source.get("ontology_path"), list)
            or not source.get("ontology_path")
            or not evidence_sources
        ):
            continue
        row = with_company_role({
            **source,
            "ticker": identity[1],
            "stock_code": identity[1],
            "market": identity[0],
            "exchange": identity[0],
            "company_description": str(source.get("company_description") or source.get("company_summary") or "").strip(),
            "connection_explanation": str(source.get("connection_explanation") or source.get("relationship_reason") or source.get("reason") or "").strip(),
            "evidence_url": evidence_url,
            "evidence_sources": evidence_sources,
            **logo_fields,
            "market_snapshot": _actual_market_snapshot(source, candidate),
            "ranking_effect": "none",
            "investment_recommendation": False,
        })
        if not all((
            company,
            row["company_description"],
            row["connection_explanation"],
            evidence_url,
            row.get("company_role_public") is True,
        )):
            continue
        seen.add(identity)
        rows.append(row)
    return select_role_diverse_company_projection(rows, limit=10)


def _live_card(candidate: dict, observed_at: datetime) -> dict:
    context = candidate.get("context_research") or {}
    keywords = []
    for source in candidate.get("related_keywords") or candidate.get("keywords") or []:
        if isinstance(source, dict):
            text = normalized_keyword_text(source.get("text"))
            row = dict(source)
        else:
            text = normalized_keyword_text(source)
            row = {}
        if text and text not in {item["text"] for item in keywords}:
            keywords.append({**row, "text": text, "affects_live_rank": False})
        if len(keywords) == 5:
            break
    companies = _live_company_rows(candidate)
    company_names = {row["company"] for row in companies}
    keyword_names = {row["text"] for row in keywords}
    links = [
        dict(row)
        for row in candidate.get("keyword_company_links") or []
        if row.get("company") in company_names and row.get("keyword") in keyword_names
    ]
    sparse = _observed_sparse_series(candidate, observed_at)
    story = candidate.get("trend_story") or {}
    diffusion = story.get("diffusion") or {}
    stage = diffusion.get("trend_stage") or {"key": "detected", "label": "포착", "index": 1}
    evidence_urls = [
        str(url) for url in context.get("evidence_urls") or []
        if str(url).startswith(("http://", "https://"))
    ]
    return {
        "event_key": candidate.get("event_key"),
        "display_name": candidate.get("display_name"),
        "topic": candidate.get("topic"),
        "canonical_topic": candidate.get("canonical_topic"),
        "lane": candidate.get("lane"),
        "broad_category": candidate.get("broad_category"),
        "category": candidate.get("category"),
        "category_label": candidate.get("category_label"),
        "lifecycle": candidate.get("lifecycle"),
        "lifecycle_reason": candidate.get("lifecycle_reason"),
        "source_badge": candidate.get("source_badge"),
        "sources": sorted(
            source for source in (candidate.get("latest_source_ranks") or {})
            if source in {"x", "google_trends"}
        ),
        "latest_source_ranks": candidate.get("latest_source_ranks") or {},
        "first_seen_at": candidate.get("first_seen_at"),
        "last_seen_at": candidate.get("last_seen_at"),
        "is_current": candidate.get("is_current") is True,
        "context_research": context,
        "disclaimer": candidate.get("disclaimer"),
        "series": [dict(row) for row in candidate.get("series") or []],
        "selection_origin": "canonical_validated_home_feed",
        "data_mode": "observed_live",
        "currently_observed": candidate.get("is_current") is True,
        "observed_within_24h": True,
        "trend_definition": str(candidate.get("trend_definition") or candidate.get("phenomenon_summary") or context.get("why_now") or "").strip(),
        "why_now": str(context.get("why_now") or "").strip(),
        "evidence_urls": evidence_urls,
        "trend_stage": stage,
        "attention_windows": sparse.pop("attention_windows"),
        "visualization_series": sparse,
        "series_metric": {
            "key": "normalized_attention_index",
            "label": "언급량 추이 · 관심지수",
            "is_absolute_mention_count": False,
        },
        "keywords": keywords,
        "related_keywords": keywords,
        "keyword_status": "ready",
        "companies": companies,
        "company_role_category_count": len({
            str(company.get("company_role_category") or "").strip()
            for company in companies
            if str(company.get("company_role_category") or "").strip()
        }),
        "company_card_status": "ready",
        "frontend_readiness_status": "ready",
        "keyword_company_links": links,
        "ranking_effect": "none",
    }


def _valid_previous_live_feed(feed: dict | None) -> bool:
    return bool(
        isinstance(feed, dict)
        and feed.get("schema_version") == "trzip-presentation-feed-v4"
        and feed.get("selection_policy") == "validated_live_home_feed_v1"
        and (feed.get("transition") or {}).get("synthetic_data_used") is False
        and all(item.get("data_mode") == "observed_live" for item in feed.get("items") or [])
    )


def build_presentation_feed(
    intelligence: dict,
    *,
    previous_feed: dict | None = None,
) -> dict:
    """Project at most ten complete observed cards; never pad with fixtures."""

    from .processing_cycle import complete_card_gate

    observed_at = _parse_observed_at((intelligence.get("window") or {}).get("to")) or datetime.now(UTC)
    candidates = list(intelligence.get("unified_ranking") or [])
    by_key = {str(item.get("event_key") or ""): item for item in candidates}
    home_keys = [
        str(summary.get("event_key") or "")
        for summary in intelligence.get("home_top10") or []
    ]
    home_key_set = set(home_keys)
    remaining = sorted(
        (
            item for item in candidates
            if str(item.get("event_key") or "") not in home_key_set
            and item.get("lane") == "main"
            and item.get("home_eligible") is True
        ),
        key=lambda item: (
            -float(item.get("_home_selection_score") or item.get("score") or 0.0),
            int(item.get("observed_rank") or 10**9),
            str(item.get("event_key") or ""),
        ),
    )
    ordered_candidates = [
        by_key.get(event_key)
        for event_key in home_keys
        if by_key.get(event_key) is not None
    ] + remaining
    seen_candidates = set()
    items = []
    for candidate in ordered_candidates:
        event_key = str(candidate.get("event_key") or "")
        if not event_key or event_key in seen_candidates:
            continue
        seen_candidates.add(event_key)
        if not complete_card_gate(candidate, observed_at=observed_at)["ready"]:
            continue
        projected = _live_card(candidate, observed_at)
        # Projection can remove malformed or duplicate company rows.  Re-run
        # the public contract after that loss so one bad card does not abort
        # the whole daily publication or hide later complete candidates.
        if complete_card_gate(
            projected,
            observed_at=observed_at,
            public_projection=True,
        )["ready"]:
            items.append(projected)
        if len(items) == 10:
            break
    # Empty is an honest result.  Previous live cards are not reused here;
    # source-health protection belongs to the remote publish layer.
    fallback_used = False
    previous_items = list((previous_feed or {}).get("items") or [])
    for position, item in enumerate(items, 1):
        item["presentation_position"] = position
        item["presentation_rank"] = position
        item["current_rank"] = position
        item["rank_movement"] = _presentation_movement(
            item,
            position,
            previous_items,
        )
    return {
        "schema_version": "trzip-presentation-feed-v4",
        "observed_at": observed_at.isoformat(),
        "status": "ready" if items else "empty",
        "frontend_default": True,
        "selection_policy": "validated_live_home_feed_v1",
        "logo_policy": {
            "version": LOGO_QUALITY_POLICY,
            "avatar_size_px": 44,
            "minimum_raster_dimension_px": LOGO_MINIMUM_DIMENSION,
            "vector_assets_allowed": True,
            "low_resolution_fallback": "initials",
            "runtime_probe_for_generic_favicons": False,
            "official_page_resolver_required": True,
            "asset_sha256_required": True,
        },
        "items": items,
        "transition": {
            "enabled": True,
            "policy": "validated_live_home_feed_no_padding",
            "window_hours": 24,
            "missing_hours_allowed": True,
            "synthetic_data_used": False,
            "supplemental_display_data_used": False,
            "canonical_ranking_affected": False,
            "fallback": "none_empty_is_published_honestly",
            "fallback_used": fallback_used,
            "padding_forbidden": True,
        },
    }
