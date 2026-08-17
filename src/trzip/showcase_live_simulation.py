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
from .company_relation_graph import resolve_listed_parent


SCHEMA_VERSION = "trzip-showcase-live-simulation-v1"
MODE = "showcase_live_simulation"
KST = timezone(timedelta(hours=9))

# A presentation card is not allowed to become a production relation set just
# because every row names a listed company.  The relation needs a reviewed
# ontology edge that names the trend-to-company connection, with a source that
# can be inspected later.  This is intentionally stricter than the legacy
# showcase contract below: that data is a recorded demonstration, not a source
# for new public company relationships.
QUALIFIED_ONTOLOGY_RELATION_TIERS = frozenset({"direct", "value_chain"})
QUALIFIED_ONTOLOGY_EVIDENCE_SCOPE = "ontology_verified_trend_to_company_relation"
MINIMUM_PUBLISHABLE_COMPANY_COUNT = 10
MINIMUM_PUBLISHABLE_COMPANY_ROLE_COUNT = 3
KOSDAQ_STOCK_CODES = frozenset({
    "030530", "035760", "035900", "041510", "048910", "053030", "067160",
    "080160", "086980", "091700", "095700", "097520", "122870", "136480",
    "160550", "195500", "206560", "207760", "253450", "263720", "277810",
    "299900", "417180", "419530", "491000",
})


def exact_domestic_market(stock_code: str) -> str:
    """Return the public exchange segment instead of the generic KRX operator name."""

    return "KOSDAQ" if str(stock_code) in KOSDAQ_STOCK_CODES else "KOSPI"


def audit_relation_set_for_publication(companies: Iterable[dict]) -> dict:
    """Return a deterministic admission receipt for one trend's companies.

    This is deliberately a *relation* gate, separate from trend ranking.  It
    prevents a UI requirement such as "show ten companies" from turning broad
    sector similarity or an identity homepage into a claimed business link.
    """

    rows = [dict(company) for company in companies]
    qualified_rows = [
        row
        for row in rows
        if row.get("relation_tier") in QUALIFIED_ONTOLOGY_RELATION_TIERS
        and row.get("evidence_scope") == QUALIFIED_ONTOLOGY_EVIDENCE_SCOPE
        and str(row.get("relationship_evidence_url") or "").strip()
        and str(row.get("connection_explanation") or "").strip()
    ]
    stock_codes = [str(row.get("stock_code") or "").strip() for row in qualified_rows]
    roles = {
        str(row.get("company_role_category") or "").strip()
        for row in qualified_rows
        if str(row.get("company_role_category") or "").strip()
    }
    failures = []
    if len(qualified_rows) < MINIMUM_PUBLISHABLE_COMPANY_COUNT:
        failures.append("minimum_ten_ontology_verified_companies")
    if len(set(stock_codes)) != len(qualified_rows) or not all(stock_codes):
        failures.append("unique_listed_company_identity")
    if len(roles) < MINIMUM_PUBLISHABLE_COMPANY_ROLE_COUNT:
        failures.append("minimum_three_company_role_categories")
    return {
        "status": "ready" if not failures else "review_required",
        "qualified_company_count": len(qualified_rows),
        "qualified_role_count": len(roles),
        "qualified_stock_codes": stock_codes,
        "failures": failures,
    }


def audit_showcase_relation_coverage(payload: dict) -> list[dict]:
    """Audit each showcase card without changing its display order or rank."""

    return [
        {
            "event_key": str(card.get("event_key") or ""),
            **audit_relation_set_for_publication(card.get("companies") or []),
        }
        for card in payload.get("cards") or []
    ]

SHOWCASE_SELECTION = (
    ("대한민국 광복절", "대한독립만세", "public_event"),
    ("개기일식", "개기일식", "astronomy"),
    # The source-row identity is retained for the recorded showcase input;
    # the public scenario is a separate K-pop discovery card.
    ("AC 밀란 vs 맨유", "리센느", "music"),
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
        "music_performance",
        "리센느의 신곡·무대·멤버 콘텐츠를 함께 찾아보는 K-pop 팬덤 관심 흐름입니다.",
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
    "AC 밀란 vs 맨유": ("리센느", "신곡", "음악방송", "멤버콘텐츠", "팬미팅"),
    "페르세우스 유성우": ("유성우", "별똥별", "극대기", "천체촬영", "관측명소"),
    "한화 vs 삼성": ("프로야구", "야구중계", "선발투수", "경기결과", "야구직관"),
    "둠스데이": ("어벤져스", "마블영화", "MCU", "히어로", "개봉정보"),
    "말복": ("삼계탕", "보양식", "복날음식", "간편식", "닭고기"),
    "그래미 어워드": ("시상식", "수상작", "라이브무대", "레드카펫", "음악산업"),
    "ufc 330": ("격투기", "대진표", "타이틀전", "경기중계", "하이라이트"),
    "코믹월드": ("코스프레", "동인행사", "굿즈", "일러스트", "행사티켓"),
}


def _listed_parent_card(
    entity: str,
    *,
    role: str,
    homepage: str,
    explanation: str,
) -> tuple:
    """Create a display row from the sourced corporate-relation graph.

    This prevents a future card author from treating a platform's founder,
    search visibility, or similarly named company as a listed parent.
    """

    resolution = resolve_listed_parent(entity)
    if resolution.get("status") != "resolved":
        raise ValueError(f"listed parent could not be resolved for {entity}")
    return (
        str(resolution["company"]),
        str(resolution["ticker"]),
        role,
        homepage,
        explanation,
        str(resolution["market"]),
        "direct",
        str(resolution["evidence_urls"][-1]),
        resolution,
    )


COMPANY_CARDS = {
    "대한민국 광복절": (
        # 광복절은 특정 한 기업의 수혜를 단정할 수 없는 기념일입니다. 따라서
        # 역사 콘텐츠의 제작·상영, 디지털 탐색, 실제 방문 이동처럼 사용자가
        # 확인하는 접점만 역할별로 분리하고, 일반 산업 유사성은 넣지 않습니다.
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "독립운동·근현대사 소재의 영화·방송 콘텐츠를 제작·유통하는 접점"),
        ("CJ CGV", "079160", "distribution", "https://corp.cgv.co.kr/", "역사 소재 영화의 국내 극장 상영과 관람 접점"),
        ("콘텐트리중앙", "036420", "content_production", "https://www.jcontentree.com/", "영화·드라마 제작과 배급을 통한 역사 서사 콘텐츠 접점"),
        ("덱스터", "206560", "content_production", "https://dexterstudios.com/", "영화·드라마의 시각효과 제작을 통한 역사 콘텐츠 제작 생태계 접점"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "독립운동가·기념일 정보와 역사 콘텐츠를 찾아보는 디지털 탐색 접점"),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "뉴스·웹툰·창작 콘텐츠를 통해 기념일 정보를 소비하는 디지털 접점"),
        ("KT", "030200", "platform_service", "https://corp.kt.com/", "IPTV·온라인 미디어를 통한 역사·기념 콘텐츠 시청 접점"),
        ("LG유플러스", "032640", "platform_service", "https://www.lguplus.com/", "IPTV·모바일 미디어를 통한 기념 콘텐츠 시청 접점"),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/", "독립유적·기념관을 찾는 국내 역사문화 방문의 여행 접점"),
        ("모두투어", "080160", "event_sponsorship", "https://www.modetour.com/", "독립유적·기념관을 찾는 국내 역사문화 방문의 여행 접점"),
    ),
    "개기일식": (
        ("삼성전자", "005930", "manufacturing_development", "https://www.samsung.com/sec/", "태양필터를 사용한 일식 기록과 관측 결과 공유에 쓰이는 스마트폰 카메라 기기 축입니다."),
        ("LG이노텍", "011070", "raw_materials_components", "https://www.lginnotek.com/", "스마트폰 카메라 모듈과 광학부품을 공급하는 촬영 장비 공급망 축입니다."),
        ("삼성전기", "009150", "raw_materials_components", "https://www.samsungsem.com/", "카메라 모듈에 쓰이는 정밀 기판·부품을 공급하는 광학부품 축입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "카카오맵과 모바일 커뮤니티에서 관측 장소·시간을 확인하고 현장 기록을 공유하는 플랫폼 접점입니다."),
        ("Apple", "AAPL", "manufacturing_development", "https://www.apple.com/", "일식 기록에 쓰이는 스마트폰 카메라와 야간·고해상도 촬영 기능을 제공하는 기기 축입니다.", "NASDAQ", "adjacent", "https://support.apple.com/guide/iphone/take-photos-iph1a3c5b3f/ios"),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "관측 시각·안전 수칙·천문대 정보를 찾아보는 검색과 커뮤니티 탐색 축입니다."),
        ("SOOP", "067160", "platform_service", "https://corp.sooplive.co.kr/", "천문 관측 후기와 실시간 영상 콘텐츠를 함께 보는 커뮤니티 접점입니다."),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/", "개기일식 관측 명소와 체험형 여행을 찾는 이동·여행 수요 축입니다."),
        ("모두투어", "080160", "event_sponsorship", "https://www.modetour.com/", "해외 관측지와 천문 현상 여행 일정을 탐색하는 여행 수요 축입니다."),
        ("노랑풍선", "104620", "event_sponsorship", "https://www.ybtour.co.kr/", "관측 목적지와 일정형 여행 상품을 비교하는 여행 탐색 흐름과 맞닿아 있습니다."),
    ),
    "AC 밀란 vs 맨유": (
        ("하이브", "352820", "content_production", "https://hybecorp.com/", "아티스트·음반·공연 콘텐츠를 제작하는 K-pop 팬덤 콘텐츠 산업의 제작 축입니다."),
        ("JYP Ent.", "035900", "content_production", "https://www.jype.com/", "아티스트와 음원·무대 콘텐츠를 제작하는 K-pop 팬덤 콘텐츠 산업의 제작 축입니다."),
        ("SM", "041510", "content_production", "https://www.smentertainment.com/", "글로벌 아티스트 IP와 팬 콘텐츠를 제작하는 음악 콘텐츠 제작 축입니다."),
        ("SBS", "034120", "distribution", "https://www.sbs.co.kr/", "음악방송과 아티스트 무대 영상을 유통해 팬덤의 신곡·무대 탐색이 이어지는 미디어 접점입니다."),
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "음악방송·무대·공연 콘텐츠를 제작·유통하는 미디어 접점입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "아티스트 검색·클립·팬 콘텐츠를 탐색하는 플랫폼 접점입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "음원·아티스트·팬 커뮤니티 콘텐츠를 소비하는 플랫폼 접점입니다."),
        ("SOOP", "067160", "distribution", "https://corp.sooplive.co.kr/", "팬 방송과 라이브 콘텐츠가 유통되는 실시간 커뮤니티 접점입니다."),
        ("KT", "030200", "distribution", "https://corp.kt.com/", "모바일·IPTV 기반으로 공연과 영상 콘텐츠를 소비하는 디지털 유통 축입니다."),
        ("LG유플러스", "032640", "distribution", "https://www.lguplus.com/", "아이돌·공연 중심의 미디어 콘텐츠를 제공하는 디지털 유통 축입니다."),
    ),
    "페르세우스 유성우": (
        # A meteor shower is an observation and shooting journey. Search is
        # not a sufficient relationship by itself, so Naver is intentionally
        # excluded. The ontology retains the X -> xAI -> SpaceX ownership path
        # as contextual evidence, but SpaceX lacks a complete reported-ROE
        # record for this public market contract and is therefore not rendered
        # as a public company card rather than receiving a fabricated metric.
        ("삼성전자", "005930", "manufacturing_development", "https://www.samsung.com/sec/", "야간 모드·장노출을 지원하는 스마트폰 카메라로 별똥별 촬영 수요와 맞닿아 있습니다."),
        ("LG이노텍", "011070", "raw_materials_components", "https://www.lginnotek.com/", "스마트폰용 카메라 모듈과 광학부품을 개발·공급하는 국내 상장기업입니다."),
        ("SBS", "034120", "platform_service", "https://www.sbs.co.kr/", "천문 현상과 관측 시기를 영상·뉴스로 설명하고 시청자가 관련 정보를 다시 찾게 하는 미디어 탐색 접점입니다."),
        ("Apple", "AAPL", "manufacturing_development", "https://www.apple.com/", "야간 모드·장노출 촬영 기능을 제공하는 스마트폰 카메라 기기로 관측 기록 수요와 맞닿아 있습니다.", "NASDAQ", "adjacent", "https://support.apple.com/guide/iphone/take-night-mode-photos-iph1a3c5b3f/ios"),
        ("노랑풍선", "104620", "event_sponsorship", "https://www.ybtour.co.kr/", "야간 관측 명소와 체험형 여행을 비교하는 이동·여행 수요의 인접 여행사입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "뉴스·오픈채팅·지도 서비스에서 관측 장소와 사진·후기를 공유하는 국내 커뮤니티 접점입니다."),
        ("Alphabet", "GOOGL", "platform_service", "https://abc.xyz/", "YouTube를 통해 관측 시간·촬영법·실시간 영상을 소비하는 영상 플랫폼 축입니다.", "NASDAQ", "contextual", "https://about.youtube/"),
        ("Meta Platforms", "META", "platform_service", "https://about.meta.com/", "Instagram에서 관측 사진과 릴스가 공유·확산되는 소셜 플랫폼 축입니다.", "NASDAQ", "contextual", "https://about.meta.com/technologies/instagram/"),
        ("하나투어", "039130", "event_sponsorship", "https://www.hanatourcompany.com/", "별 관측 명소를 찾고 이동하는 관측 여행 수요와 연결됩니다."),
        ("모두투어", "080160", "event_sponsorship", "https://www.modetour.com/", "야간 관측 명소·체험형 여행을 탐색하는 수요의 인접 여행사입니다."),
    ),
    "한화 vs 삼성": (
        ("한화", "000880", "ownership_investment", "https://www.hanwhacorp.co.kr/", "한화 이글스의 구단주 기업으로 경기·선수·직관 관심과 직접 맞닿아 있습니다."),
        ("삼성물산", "028260", "ownership_investment", "https://www.samsungcnt.com/", "삼성 라이온즈 명칭으로 형성되는 삼성 브랜드와 스포츠 관심 맥락을 확인하는 축입니다."),
        ("SBS", "034120", "distribution", "https://www.sbs.co.kr/", "프로야구 경기·하이라이트를 방송 콘텐츠로 유통하는 스포츠 미디어 접점입니다."),
        ("CJ ENM", "035760", "distribution", "https://www.cjenm.com/", "TVING·스포츠 채널을 통한 프로야구 중계와 하이라이트 소비의 미디어 축입니다."),
        ("SOOP", "067160", "distribution", "https://corp.sooplive.co.kr/", "경기 라이브와 팬 방송을 소비하는 스포츠 스트리밍 접점입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "경기 일정·기록·뉴스·팬 콘텐츠를 탐색하는 스포츠 정보 플랫폼입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "뉴스와 대화형 커뮤니티로 경기 이슈를 공유하는 디지털 접점입니다."),
        ("KT", "030200", "distribution", "https://corp.kt.com/", "모바일·IPTV 환경에서 스포츠 영상과 경기 정보를 소비하는 미디어 유통 축입니다."),
        ("LG유플러스", "032640", "distribution", "https://www.lguplus.com/", "모바일·IPTV 환경에서 스포츠 영상과 경기 정보를 소비하는 미디어 유통 축입니다."),
        ("SK텔레콤", "017670", "platform_service", "https://www.sktelecom.com/", "모바일 환경의 실시간 경기 시청·클립 소비를 뒷받침하는 통신·미디어 접점입니다."),
    ),
    "둠스데이": (
        ("월트 디즈니 컴퍼니", "DIS", "ownership_investment", "https://thewaltdisneycompany.com/", "마블 스튜디오와 어벤져스 IP를 보유·제작·배급하는 핵심 권리사입니다.", "NYSE"),
        ("CJ CGV", "079160", "distribution", "https://corp.cgv.co.kr/", "마블 영화의 국내 극장 상영과 예매 경험이 이어지는 멀티플렉스 유통 축입니다."),
        ("콘텐트리중앙", "036420", "distribution", "https://www.jcontentree.com/", "영화·드라마의 제작·배급을 수행하는 국내 스크린 콘텐츠 유통 생태계 접점입니다."),
        ("쇼박스", "086980", "distribution", "https://www.showbox.co.kr/", "국내 영화 투자·배급을 수행하는 극장 개봉 콘텐츠 유통 축입니다."),
        ("NEW", "160550", "distribution", "https://www.its-new.co.kr/", "영화·드라마의 투자·배급을 수행하는 국내 콘텐츠 유통 축입니다."),
        ("덱스터", "206560", "content_production", "https://dexterstudios.com/", "영화·시리즈의 시각효과를 제작하는 스크린 콘텐츠 제작 생태계 접점입니다."),
        ("CJ ENM", "035760", "content_production", "https://www.cjenm.com/", "영화·드라마·엔터테인먼트 콘텐츠를 제작·유통하는 미디어 제작 축입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "영화 검색·예고편·팬 콘텐츠를 찾아보는 디지털 탐색 플랫폼입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "웹툰·웹소설·엔터테인먼트 콘텐츠를 소비하고 대화하는 플랫폼 접점입니다."),
        ("KT", "030200", "platform_service", "https://corp.kt.com/", "IPTV와 모바일 환경에서 영화·시리즈를 소비하는 미디어 서비스 접점입니다."),
    ),
    "말복": (
        ("CJ제일제당", "097950", "manufacturing_development", "https://www.cj.co.kr/", "삼계탕·보양식 HMR을 제조하는 복날 식품 제조 축입니다."),
        ("하림", "136480", "manufacturing_development", "https://www.harim.com/", "닭고기 가공과 삼계탕 제품을 만드는 복날 식품 제조 축입니다."),
        ("대상", "001680", "manufacturing_development", "https://www.daesang.com/", "간편식·보양식 제품을 만드는 계절 식품 제조 축입니다."),
        ("마니커에프앤지", "195500", "raw_materials_components", "https://www.manikerfng.com/", "닭고기 가공과 HMR 원료를 공급하는 보양식 공급망 축입니다."),
        ("사조대림", "003960", "manufacturing_development", "https://dr.sajo.co.kr/eng/intro/company_ci.asp", "냉장·냉동 간편식을 제조·유통하는 복날 식품 제조 축입니다."),
        ("풀무원", "017810", "manufacturing_development", "https://www.pulmuone.co.kr/", "국·탕·간편식을 포함한 가정간편식을 제조하는 계절 식생활 수요의 제조 축입니다."),
        ("오뚜기", "007310", "manufacturing_development", "https://www.ottogi.co.kr/", "국·탕·조리식품을 포함한 가정간편식을 제조하는 식품 제조 축입니다."),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/", "보양식과 닭고기 상품을 판매하는 대형 리테일 접점입니다."),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/", "편의점·슈퍼에서 보양식 간편식을 판매하는 생활 리테일 접점입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "레시피·맛집·구매 정보를 찾아보는 복날 식생활 정보 탐색 플랫폼입니다."),
    ),
    "그래미 어워드": (
        ("하이브", "352820", "content_production", "https://hybecorp.com/", "글로벌 아티스트·음반을 제작하는 음악 산업의 제작 축입니다."),
        ("JYP Ent.", "035900", "content_production", "https://www.jype.com/", "K-pop 아티스트·음반을 제작하는 음악 산업의 제작 축입니다."),
        ("SM", "041510", "content_production", "https://www.smentertainment.com/", "글로벌 음악 IP와 아티스트 콘텐츠를 제작하는 음악 제작 축입니다."),
        ("SBS", "034120", "distribution", "https://www.sbs.co.kr/", "음악방송과 아티스트 무대 영상을 유통해 시상식·수상작 탐색이 이어지는 미디어 접점입니다."),
        ("CJ ENM", "035760", "distribution", "https://www.cjenm.com/", "음악 방송·공연·시상식 관련 콘텐츠를 유통하는 미디어 축입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "음원·아티스트·팬 콘텐츠를 소비하고 공유하는 플랫폼 접점입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "아티스트 라이브·클립·팬 콘텐츠를 탐색하는 플랫폼 접점입니다."),
        ("SOOP", "067160", "platform_service", "https://corp.sooplive.co.kr/", "공연·리액션·팬 방송을 소비하는 실시간 커뮤니티 플랫폼 접점입니다."),
        ("KT", "030200", "distribution", "https://corp.kt.com/", "모바일·IPTV를 통해 음악·공연 영상을 소비하는 미디어 유통 축입니다."),
        ("LG유플러스", "032640", "distribution", "https://www.lguplus.com/", "모바일·IPTV 환경에서 음악·공연 콘텐츠를 소비하는 미디어 유통 축입니다."),
    ),
    "ufc 330": (
        # The first five rows are rights-holder and official-partner edges.  The
        # remaining rows are deliberately labeled as Korean discovery/viewing
        # surfaces; they are not represented as UFC media-rights holders.
        ("TKO 그룹 홀딩스", "TKO", "ownership_investment", "https://tkogrp.com/", "UFC를 소유·운영하는 상장 모회사입니다.", "NYSE", "direct", "https://tkogrp.com/"),
        ("CJ ENM", "035760", "distribution", "https://www.cjenm.com/", "TVING과 tvN SPORTS를 통해 2029년까지 UFC의 국내 독점 중계를 맡는 권리사입니다.", "KRX", "direct", "https://kr.ufc.com/news/cj-enm-ufc-hangug-junggyegwon-gyeyag-yeonjang"),
        ("AB 인베브", "BUD", "brand_marketing", "https://www.ab-inbev.com/", "UFC의 공식 글로벌 맥주 파트너로서 대회·중계·디지털 콘텐츠에 참여합니다.", "NYSE", "direct", "https://www.ufc.com/news/ufc-and-anheuser-busch-announce-multiyear-partnership"),
        ("Monster Beverage", "MNST", "brand_marketing", "https://investors.monsterbevcorp.com/", "UFC의 공식 에너지음료 파트너로서 대회 현장과 디지털 콘텐츠에 노출되는 글로벌 파트너입니다.", "NASDAQ", "direct", "https://www.ufc.com/partners"),
        ("SBS", "034120", "platform_service", "https://www.sbs.co.kr/", "대진표·경기 결과·격투기 콘텐츠를 영상과 뉴스로 탐색하는 국내 미디어 접점입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "대진표·경기 결과·하이라이트 정보를 찾아보는 스포츠 정보 탐색 플랫폼입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "경기 뉴스와 팬 대화를 공유하는 디지털 커뮤니티 접점입니다."),
        ("SOOP", "067160", "platform_service", "https://corp.sooplive.co.kr/", "격투기 시청 후기와 팬 방송을 소비하는 실시간 커뮤니티 접점입니다."),
        ("KT", "030200", "distribution", "https://corp.kt.com/", "모바일·IPTV 환경에서 스포츠 영상과 관련 콘텐츠를 소비하는 미디어 유통 축입니다."),
        ("LG유플러스", "032640", "distribution", "https://www.lguplus.com/", "모바일·IPTV 환경에서 스포츠 영상과 관련 콘텐츠를 소비하는 미디어 유통 축입니다."),
    ),
    "코믹월드": (
        ("대원미디어", "048910", "content_production", "https://www.daewonmedia.com/", "애니메이션·캐릭터 IP를 유통하는 행사 콘텐츠 축입니다."),
        ("미스터블루", "207760", "content_production", "https://www.mrbluecorp.com/", "웹툰·만화 콘텐츠를 제공하는 팬 창작 콘텐츠 축입니다."),
        ("SAMG엔터", "419530", "brand_marketing", "https://samg.net/", "캐릭터 IP와 굿즈 사업을 전개하는 캐릭터 소비 접점입니다."),
        ("디앤씨미디어", "263720", "content_production", "https://www.dncmedia.co.kr/", "웹소설·웹툰 IP를 제작·유통하는 팬 콘텐츠 제작 축입니다."),
        ("핑거스토리", "417180", "content_production", "https://www.fingerstory.com/", "웹툰·웹소설 콘텐츠를 제공하는 디지털 만화 콘텐츠 축입니다."),
        ("NAVER", "035420", "platform_service", "https://www.navercorp.com/", "웹툰·팬 창작 콘텐츠를 탐색하고 공유하는 플랫폼 접점입니다."),
        ("카카오", "035720", "platform_service", "https://www.kakaocorp.com/", "웹툰·캐릭터 콘텐츠를 소비하고 공유하는 플랫폼 접점입니다."),
        ("이마트", "139480", "retail_sales", "https://company.emart.com/", "캐릭터·컬처 팝업과 굿즈 소비가 이어지는 생활 리테일 접점입니다."),
        ("GS리테일", "007070", "retail_sales", "https://www.gsretail.com/", "캐릭터 협업 상품과 굿즈를 접하는 생활 리테일 접점입니다."),
        ("롯데쇼핑", "023530", "retail_sales", "https://www.lotteshopping.com/", "쇼핑몰·백화점에서 캐릭터 행사와 굿즈 소비가 이뤄지는 리테일 접점입니다."),
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
        for entry in COMPANY_CARDS[event_key]:
            company, stock_code, role, homepage, explanation, *market_values = entry
            market = str(
                market_values[0]
                if market_values
                else exact_domestic_market(stock_code)
            )
            relation_tier = str(market_values[1] if len(market_values) > 1 else "contextual")
            relationship_evidence_url = str(market_values[2] if len(market_values) > 2 else homepage)
            resolution = market_values[3] if len(market_values) > 3 else None
            company_row = {
                "company": company,
                "stock_code": stock_code,
                "market": market,
                "company_role_category": role,
                "company_role_label": COMPANY_ROLE_LABELS[role],
                "relationship_status": "reconstructed_demo",
                "relation_tier": relation_tier,
                "relationship_evidence_url": relationship_evidence_url,
                "connection_explanation": explanation,
                "relationship_reason": explanation,
                "company_identity_url": homepage,
                "evidence_scope": "company_identity_only_not_observed_trend_relation",
                "ranking_effect": "none",
            }
            if isinstance(resolution, dict):
                company_row["corporate_relation_path"] = list(resolution["path"])
                company_row["corporate_relation_types"] = list(resolution["relation_types"])
                company_row["corporate_relation_evidence_urls"] = list(resolution["evidence_urls"])
                company_row["listing_evidence_url"] = str(resolution["listing_evidence_url"])
            companies.append(company_row)
        roles = {row["company_role_category"] for row in companies}
        # Every public card exposes the same exploration depth.  The ontology
        # decides which ten rows qualify; the presentation cannot leave one
        # trend looking unfinished with fewer related companies.
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
        "display_status": "NOW",
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
        if len(companies) != 10 or len(set(stock_codes)) != len(companies):
            raise ValueError("showcase requires ten unique listed-company identities")
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
