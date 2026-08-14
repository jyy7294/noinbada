"""Reviewed publication feed consumed by the MVP frontend.

This feed fixes the ten editorially approved observed events for the current
MVP presentation.  It does not replace or mutate the canonical X/Google
ranking.  Reference enrichment is allowed to improve display detail only.
"""

from __future__ import annotations

from .company_roles import with_company_role
from .editorial_review import KEYWORDS, _verified_company_rows
from .keyword_policy import keyword_fits_public_label, normalized_keyword_text


VERIFIED_AT = "2026-08-14T00:00:00+00:00"
GOOGLE_TRENDS_KR = "https://trends.google.com/trending?geo=KR"


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
        "company_key": "천체관측장비",
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


def _key(value: object) -> str:
    return "".join(str(value or "").casefold().split())


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
    if not all((company, ticker, market, description, reason)):
        raise ValueError(f"{display_name}: incomplete listed-company identity for {company or 'unknown'}")
    if not evidence_url.startswith(("http://", "https://")):
        raise ValueError(f"{display_name}: public company evidence URL is required for {company}")

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
        "candidate_rank": position,
        "verification_status": "evidence_verified",
        "verified_at": source.get("verified_at") or VERIFIED_AT,
        "review_status": "reviewed_reference",
        "ranking_effect": "none",
        "investment_recommendation": False,
    })
    if not row.get("company_role_public"):
        raise ValueError(f"{display_name}: explicit public company role is required for {company}")
    return row


def _company_rows(display_name: str, details: dict) -> list[dict]:
    if details.get("company_key"):
        rows = _verified_company_rows(details["company_key"], verified_at=VERIFIED_AT)
        return [
            _presentation_company_row(display_name, position, row)
            for position, row in enumerate(rows, 1)
            if row.get("company_role_public")
        ]
    return [
        _manual_company_row(display_name, position, source)
        for position, source in enumerate(MANUAL_COMPANIES.get(display_name, ()), 1)
    ]


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
            or "관측일 확인 중"
        ),
        "attention_lift": diffusion.get("attention_lift") or {
            "status": "unavailable",
            "metric": "normalized_attention_index_change",
            "value": None,
            "unit": "percent",
            "label": "언급량 비교 축적 중",
        },
        "attention_windows": diffusion.get("attention_windows") or [
            {
                "key": key,
                "label": label,
                "metric": "normalized_attention_index_change",
                "status": "unavailable",
                "percent": None,
                "basis": "previous_equal_period_score",
                "is_absolute_mention_count": False,
            }
            for key, label in (("1w", "1주"), ("1m", "1개월"), ("3m", "3개월"))
        ],
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
        "series": (candidate or {}).get("series") or [],
    }


def build_presentation_feed(intelligence: dict) -> dict:
    """Return the exact reviewed Top10 in the order approved by the user."""

    candidates = list(intelligence.get("unified_ranking") or [])
    items = [_reference_card(item, candidates) for item in REFERENCE_TOP10]
    for position, item in enumerate(items, 1):
        item["presentation_position"] = position
        item["presentation_rank"] = position
        item["current_rank"] = position
    return {
        "schema_version": "trzip-presentation-feed-v2",
        "status": "ready",
        "frontend_default": True,
        "items": items,
        "transition": {
            "enabled": False,
            "policy": "fixed_reviewed_top10_until_daily_auto_feed_is_explicitly_activated",
            "required_clean_hours": 24,
            "synthetic_data_used": False,
            "canonical_ranking_affected": False,
        },
    }
