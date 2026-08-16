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
    ("대한민국 광복절", "대한독립만세", "public_event"),
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

COMPANY_CARDS = {
    "대한민국 광복절": (
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "독립운동가·기념일 검색과 역사 콘텐츠 유통"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "기념일 뉴스·창작 콘텐츠 유통"),
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "역사·기념일 방송 콘텐츠 제작·유통"),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/", "독립유적·기념관 연계 국내여행 상품"),
        ("모두투어", "080160", "event_sponsorship", "https://www.modetour.com/", "역사문화 명소 중심 국내여행 운영"),
    ),
    "개기일식": (
        ("삼성전자", "005930", "manufacturing_development", "https://www.samsung.com/sec/", "스마트폰 카메라·천체 촬영 기기"),
        ("LG전자", "066570", "manufacturing_development", "https://www.lge.co.kr/", "관측 영상용 디스플레이·전자기기"),
        ("LG이노텍", "011070", "raw_materials_components", "https://www.lginnotek.com/", "스마트폰 카메라 모듈·광학부품"),
        ("삼성전기", "009150", "raw_materials_components", "https://www.samsungsem.com/", "카메라 모듈·정밀 광학부품"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "천문정보·관측 콘텐츠 검색 플랫폼"),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/", "천문 현상 관측 목적지 여행 상품"),
    ),
    "AC 밀란 vs 맨유": (
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "스포츠 중계 채널·OTT 콘텐츠 운영"),
        ("SOOP", "067160", "platform_service", "https://corp.sooplive.co.kr/", "축구·스포츠 라이브 스트리밍"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/", "Genie TV 스포츠 채널 유통"),
        ("LG유플러스", "032640", "platform_service", "https://www.lguplus.com/", "U+tv 스포츠 채널 유통"),
        ("제일기획", "030000", "brand_marketing", "https://www.cheil.com/", "글로벌 스포츠 행사·브랜드 마케팅"),
    ),
    "페르세우스 유성우": (
        ("삼성전자", "005930", "manufacturing_development", "https://www.samsung.com/sec/", "야간 촬영용 스마트폰 카메라·기기"),
        ("LG전자", "066570", "manufacturing_development", "https://www.lge.co.kr/", "천체 영상용 디스플레이·전자기기"),
        ("LG이노텍", "011070", "raw_materials_components", "https://www.lginnotek.com/", "야간 촬영 카메라 모듈·광학부품"),
        ("삼성전기", "009150", "raw_materials_components", "https://www.samsungsem.com/", "카메라 모듈·정밀 광학부품"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "유성우 일정·관측지 정보 검색 플랫폼"),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/", "별 관측 명소 연계 여행 상품"),
    ),
    "한화 vs 삼성": (
        ("한화", "000880", "ownership_investment", "https://www.hanwhacorp.co.kr/", "한화그룹 프로야구 구단 브랜드"),
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "프로야구 중계·하이라이트 콘텐츠"),
        ("SOOP", "067160", "platform_service", "https://corp.sooplive.co.kr/", "프로야구 라이브 스트리밍·팬 방송"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "프로야구 일정·기록·팬 콘텐츠"),
        ("제일기획", "030000", "brand_marketing", "https://www.cheil.com/", "스포츠 구단·브랜드 캠페인 기획"),
    ),
    "둠스데이": (
        ("CJ CGV", "079160", "distribution", "https://corp.cgv.co.kr/", "마블 영화 상영 멀티플렉스 운영"),
        ("콘텐트리중앙", "036420", "distribution", "https://www.jcontentree.com/", "극장·영화 콘텐츠 배급·유통"),
        ("덱스터", "206560", "content_production", "https://dexterstudios.com/", "영화·시리즈 VFX 제작"),
        ("위지윅스튜디오", "299900", "content_production", "https://www.wswgstudios.com/", "영상 콘텐츠 VFX·후반제작"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "영화 검색·예고편·팬 콘텐츠 유통"),
    ),
    "말복": (
        ("CJ제일제당", "097950", "manufacturing_development", "https://www.cj.co.kr/", "삼계탕·보양식 HMR 제조"),
        ("하림", "136480", "manufacturing_development", "https://www.harim.com/", "닭고기 가공·삼계탕 제품 제조"),
        ("대상", "001680", "manufacturing_development", "https://www.daesang.com/", "간편식·보양식 제품 제조"),
        ("마니커에프앤지", "195500", "raw_materials_components", "https://www.mnf.co.kr/", "닭고기 가공·HMR 원료 공급"),
        ("사조대림", "003960", "distribution", "https://www.sajodaerim.com/", "냉장·냉동 간편식 제조·유통"),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/", "보양식·닭고기 상품 대형마트 판매"),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/", "편의점·슈퍼 보양식 간편식 판매"),
    ),
    "그래미 어워드": (
        ("하이브", "352820", "content_production", "https://hybecorp.com/", "글로벌 아티스트·음반 제작"),
        ("JYP Ent.", "035900", "content_production", "https://www.jype.com/", "K-pop 아티스트·음반 제작"),
        ("SM", "041510", "content_production", "https://www.smentertainment.com/", "글로벌 음악 IP·아티스트 제작"),
        ("CJ ENM", "035760", "distribution", "https://www.cjenm.com/", "음악 방송·공연 콘텐츠 유통"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "음원·아티스트 콘텐츠 플랫폼"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "아티스트 라이브·팬 콘텐츠 플랫폼"),
    ),
    "ufc 330": (
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "격투기·스포츠 중계 콘텐츠 운영"),
        ("SOOP", "067160", "platform_service", "https://corp.sooplive.co.kr/", "격투기·스포츠 라이브 스트리밍"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/", "Genie TV 스포츠 채널 유통"),
        ("LG유플러스", "032640", "platform_service", "https://www.lguplus.com/", "U+tv 스포츠 채널 유통"),
        ("제일기획", "030000", "brand_marketing", "https://www.cheil.com/", "스포츠 행사·브랜드 마케팅"),
    ),
    "코믹월드": (
        ("대원미디어", "048910", "content_production", "https://www.daewonmedia.com/", "애니메이션·캐릭터 IP 유통"),
        ("미스터블루", "207760", "content_production", "https://www.mrbluecorp.com/", "웹툰·만화 콘텐츠 플랫폼"),
        ("SAMG엔터", "419530", "brand_marketing", "https://samg.net/", "캐릭터 IP·굿즈 사업"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "웹툰·팬 창작 콘텐츠 플랫폼"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "웹툰·캐릭터 콘텐츠 유통"),
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
    for order, (event_key, display_name, _universe_key) in enumerate(SHOWCASE_SELECTION, 1):
        source = by_key.get(event_key)
        if source is None:
            raise ValueError(f"showcase ranking is missing {event_key}")
        keywords = [
            {"text": text, "review_status": "showcase_approved", "ranking_effect": "none"}
            for text in KEYWORDS[event_key]
        ]
        companies = []
        for company, stock_code, role, homepage, explanation in COMPANY_CARDS[event_key]:
            companies.append({
                "company": company,
                "stock_code": stock_code,
                "market": "KRX",
                "company_role_category": role,
                "company_role_label": COMPANY_ROLE_LABELS[role],
                "relationship_status": "reconstructed_demo",
                "connection_explanation": explanation,
                "relationship_reason": explanation,
                "company_identity_url": homepage,
                "evidence_scope": "company_identity_only_not_observed_trend_relation",
                "ranking_effect": "none",
            })
        roles = {row["company_role_category"] for row in companies}
        if len(keywords) != 5 or not 5 <= len(companies) <= 10 or not 3 <= len(roles) <= 4:
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
        if not 5 <= len(companies) <= 10 or len(set(stock_codes)) != len(companies):
            raise ValueError("showcase requires five to ten unique listed-company identities")
        if not 3 <= len(roles) <= 4:
            raise ValueError("showcase requires three to four company roles")
        if any(company.get("relationship_status") != "reconstructed_demo" for company in companies):
            raise ValueError("showcase relationship provenance is invalid")
        if any(
            not str(company.get("connection_explanation") or "").strip()
            or "시연" in str(company.get("connection_explanation") or "")
            or "연결 시나리오" in str(company.get("connection_explanation") or "")
            for company in companies
        ):
            raise ValueError("showcase company explanations must be concise business descriptions")
