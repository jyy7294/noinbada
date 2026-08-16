"""Deterministic, explicitly reconstructed showcase enrichment.

The ranking inputs remain actual X/Google observations.  This module fills the
presentation-only keyword and company surfaces for a recorded demonstration;
it must never be labelled as an observed company relationship or enter the
operational live publication contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Iterable

from .company_roles import COMPANY_ROLE_LABELS


SCHEMA_VERSION = "trzip-showcase-live-simulation-v1"
MODE = "showcase_live_simulation"
KST = timezone(timedelta(hours=9))

SHOWCASE_SELECTION = (
    ("대한민국 광복절", "광복절·독립운동가", "public_event"),
    ("개기일식", "개기일식", "astronomy"),
    ("AC 밀란 vs 맨유", "AC 밀란 vs 맨유", "sports"),
    ("페르세우스 유성우", "페르세우스 유성우", "astronomy"),
    ("한화 vs 삼성", "한화 vs 삼성", "sports"),
    ("둠스데이", "둠스데이", "content"),
    ("말복", "말복", "food"),
    ("그래미 어워드", "그래미 어워드", "content"),
    ("ufc 330", "UFC 330", "sports"),
    ("코믹월드", "코믹월드", "content"),
)

SHOWCASE_PRESENTATION = {
    "대한민국 광복절": (
        "lifestyle_behavior",
        "광복절과 독립운동가를 함께 살펴보는 기념·역사 콘텐츠 흐름입니다.",
    ),
    "개기일식": (
        "technology_tool",
        "개기일식 관측 시기와 장비·촬영 정보를 함께 찾는 천문 관측 흐름입니다.",
    ),
    "AC 밀란 vs 맨유": (
        "sports_attendance",
        "AC 밀란과 맨유 경기 일정·중계·하이라이트를 함께 찾는 축구 관람 흐름입니다.",
    ),
    "페르세우스 유성우": (
        "technology_tool",
        "페르세우스 유성우 극대기와 관측 장소·촬영 정보를 찾는 천문 관측 흐름입니다.",
    ),
    "한화 vs 삼성": (
        "sports_attendance",
        "한화와 삼성 경기 일정·선발투수·직관 정보를 함께 찾는 프로야구 관람 흐름입니다.",
    ),
    "둠스데이": (
        "screen_content",
        "마블의 둠스데이 관련 작품·캐릭터·개봉 정보를 함께 찾는 콘텐츠 흐름입니다.",
    ),
    "말복": (
        "seasonal_food_ritual",
        "말복을 앞두고 보양식·간편식·닭고기 메뉴를 함께 찾는 계절 음식 흐름입니다.",
    ),
    "그래미 어워드": (
        "music_performance",
        "그래미 어워드 수상작·공연·레드카펫을 함께 찾는 음악 시상식 흐름입니다.",
    ),
    "ufc 330": (
        "sports_attendance",
        "UFC 330 대진표·타이틀전·중계 정보를 함께 찾는 격투기 관람 흐름입니다.",
    ),
    "코믹월드": (
        "place_experience",
        "코믹월드 행사 일정·코스프레·굿즈·티켓을 함께 찾는 참여형 행사 흐름입니다.",
    ),
}

KEYWORDS = {
    "대한민국 광복절": ("광복절", "독립운동", "태극기", "기념행사", "역사콘텐츠"),
    "개기일식": ("일식관측", "태양필터", "천문대", "망원경", "일식촬영"),
    "AC 밀란 vs 맨유": ("AC밀란", "맨유", "친선경기", "축구중계", "하이라이트"),
    "페르세우스 유성우": ("유성우", "별똥별", "극대기", "천체촬영", "관측명소"),
    "한화 vs 삼성": ("프로야구", "야구중계", "선발투수", "경기결과", "야구직관"),
    "둠스데이": ("어벤져스", "마블영화", "MCU", "히어로", "개봉정보"),
    "말복": ("삼계탕", "보양식", "복날음식", "간편식", "닭고기"),
    "그래미 어워드": ("시상식", "수상작", "라이브무대", "레드카펫", "음악산업"),
    "ufc 330": ("격투기", "대진표", "타이틀전", "경기중계", "하이라이트"),
    "코믹월드": ("코스프레", "동인행사", "굿즈", "일러스트", "행사티켓"),
}

COMPANY_UNIVERSES = {
    "public_event": (
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/"),
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/"),
        ("하이브", "352820", "content_production", "https://hybecorp.com/"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/"),
        ("SK텔레콤", "017670", "platform_service", "https://www.sktelecom.com/"),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/"),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/"),
        ("호텔신라", "008770", "event_sponsorship", "https://www.hotelshilla.net/"),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/"),
    ),
    "astronomy": (
        ("삼성전자", "005930", "manufacturing_development", "https://www.samsung.com/sec/"),
        ("LG전자", "066570", "manufacturing_development", "https://www.lge.co.kr/"),
        ("LG이노텍", "011070", "raw_materials_components", "https://www.lginnotek.com/"),
        ("삼성전기", "009150", "raw_materials_components", "https://www.samsungsem.com/"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/"),
        ("SK텔레콤", "017670", "platform_service", "https://www.sktelecom.com/"),
        ("호텔신라", "008770", "retail_sales", "https://www.hotelshilla.net/"),
        ("하나투어", "039130", "retail_sales", "https://www.hanatourcompany.com/"),
    ),
    "sports": (
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/"),
        ("SK텔레콤", "017670", "platform_service", "https://www.sktelecom.com/"),
        ("LG유플러스", "032640", "platform_service", "https://www.lguplus.com/"),
        ("삼성전자", "005930", "brand_marketing", "https://www.samsung.com/sec/"),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/"),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/"),
        ("호텔신라", "008770", "retail_sales", "https://www.hotelshilla.net/"),
    ),
    "content": (
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/"),
        ("하이브", "352820", "content_production", "https://hybecorp.com/"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/"),
        ("SK텔레콤", "017670", "platform_service", "https://www.sktelecom.com/"),
        ("LG유플러스", "032640", "platform_service", "https://www.lguplus.com/"),
        ("삼성전자", "005930", "brand_marketing", "https://www.samsung.com/sec/"),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/"),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/"),
    ),
    "food": (
        ("CJ제일제당", "097950", "manufacturing_development", "https://www.cj.co.kr/"),
        ("하림", "136480", "manufacturing_development", "https://www.harim.com/"),
        ("동원산업", "006040", "manufacturing_development", "https://www.dwml.co.kr/"),
        ("대상", "001680", "manufacturing_development", "https://www.daesang.com/"),
        ("풀무원", "017810", "manufacturing_development", "https://www.pulmuone.co.kr/"),
        ("마니커에프앤지", "195500", "raw_materials_components", "https://www.mnf.co.kr/"),
        ("사조대림", "003960", "distribution", "https://www.sajodaerim.com/"),
        ("한성기업", "003680", "distribution", "https://www.hsep.com/"),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/"),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/"),
    ),
}


def floor_kst_hour(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).astimezone(KST)
    return stamp.replace(minute=0, second=0, microsecond=0).isoformat()


def build_showcase_enrichment(
    ranking: Iterable[dict],
    *,
    source_observed_at: str,
    display_now: datetime | None = None,
) -> dict:
    by_key = {str(row.get("event_key") or ""): row for row in ranking}
    cards = []
    for order, (event_key, display_name, universe_key) in enumerate(SHOWCASE_SELECTION, 1):
        source = by_key.get(event_key)
        if source is None:
            raise ValueError(f"showcase ranking is missing {event_key}")
        keywords = [
            {"text": text, "review_status": "showcase_approved", "ranking_effect": "none"}
            for text in KEYWORDS[event_key]
        ]
        companies = []
        for company, stock_code, role, homepage in COMPANY_UNIVERSES[universe_key]:
            companies.append({
                "company": company,
                "stock_code": stock_code,
                "market": "KRX",
                "company_role_category": role,
                "company_role_label": COMPANY_ROLE_LABELS[role],
                "relationship_status": "reconstructed_demo",
                "relationship_reason": f"{display_name} 시연 화면의 {COMPANY_ROLE_LABELS[role]} 연결 시나리오",
                "company_identity_url": homepage,
                "evidence_scope": "company_identity_only_not_observed_trend_relation",
                "ranking_effect": "none",
            })
        roles = {row["company_role_category"] for row in companies}
        if len(keywords) != 5 or len(companies) != 10 or not 3 <= len(roles) <= 4:
            raise ValueError(f"showcase enrichment contract failed: {event_key}")
        category, trend_definition = SHOWCASE_PRESENTATION[event_key]
        cards.append({
            "event_key": event_key,
            "display_name": display_name,
            "presentation_order": order,
            "full_ledger_rank": int(source["rank"]),
            "full_ledger_score": float(source["score"]),
            "category": category,
            "trend_definition": trend_definition,
            "related_keywords": keywords,
            "companies": companies,
            "company_role_category_count": len(roles),
            "enrichment_mode": "reconstructed_demo",
            "ranking_effect": "none",
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "display_status": "시연 LIVE",
        "display_time_policy": "client_kst_floor_hour",
        "display_as_of": floor_kst_hour(display_now),
        "source_observed_at": source_observed_at,
        "source_ranking_mode": "actual_full_ledger_no_recency",
        "enrichment_mode": "reconstructed_demo",
        "cards": cards,
    }


def validate_showcase_enrichment(payload: dict) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("mode") != MODE:
        raise ValueError("showcase mode contract is invalid")
    if payload.get("enrichment_mode") != "reconstructed_demo":
        raise ValueError("showcase enrichment must remain reconstructed_demo")
    cards = payload.get("cards") or []
    if len(cards) != 10:
        raise ValueError("showcase requires exactly ten cards")
    event_keys = [str(card.get("event_key") or "") for card in cards]
    if len(set(event_keys)) != 10:
        raise ValueError("showcase event keys must be unique")
    for order, card in enumerate(cards, 1):
        companies = card.get("companies") or []
        keywords = card.get("related_keywords") or []
        roles = {
            str(company.get("company_role_category") or "")
            for company in companies
        }
        stock_codes = [str(company.get("stock_code") or "") for company in companies]
        if card.get("presentation_order") != order:
            raise ValueError("showcase order is invalid")
        if len(keywords) != 5 or len({row.get("text") for row in keywords}) != 5:
            raise ValueError("showcase requires five unique keywords")
        if len(companies) != 10 or len(set(stock_codes)) != 10:
            raise ValueError("showcase requires ten unique listed-company identities")
        if not 3 <= len(roles) <= 4:
            raise ValueError("showcase requires three to four company roles")
        if any(company.get("relationship_status") != "reconstructed_demo" for company in companies):
            raise ValueError("showcase relationship provenance is invalid")
