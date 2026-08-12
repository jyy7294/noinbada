from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .curation import CATEGORY_BY_TERM, EVENT_CONTEXT, is_sensitive_context, observed_lane
from .hourly_store import BACKFILL_END, BACKFILL_START, connect, floor_hour, generated_hour
from .value_chain import expand_value_chain
from .event_resolution import (
    GROUND_TRUTH,
    company_evidence_status,
    evaluate_resolution,
    load_company_review_overrides,
    relation_display,
    resolve_event,
)


def _company_display_state(company: dict) -> dict:
    evidence = company_evidence_status(company)
    status = evidence["verification_status"]
    if status == "excluded":
        opportunity = "excluded"
    elif status == "official_evidence" and company.get("strength") in {"direct", "indirect"}:
        opportunity = "confirmed_relationship"
    elif status == "industry_structure_only":
        opportunity = "observable_opportunity"
    else:
        opportunity = "verification_required"
    return {**evidence, "opportunity_status": opportunity}

ALIASES = {
    "두쫀쿠": "두바이 초콜릿",
    "두바이초콜릿": "두바이 초콜릿",
    "오징어게임": "오징어 게임",
    "말복": "말복",
    "삼계탕": "말복",
    "보양식": "말복",
    "#JIN_IN_BALTIMORE_D2": "진",
    "JIN LIGHTS UP CHARM CITY": "진",
    "볼티모어": "진",
}

COMPANY_REGISTRY = {
    "삼성전자": [
        {"company": "삼성전자", "stock_code": "005930", "relation_type": "listed_company_itself",
         "strength": "direct", "reason": "검색어 자체가 삼성전자 기업·종목을 직접 지칭",
         "evidence_kind": "company_official_profile", "evidence_url": "https://www.samsung.com/sec/about-us/company-info/"},
    ],
    "불닭": [
        {"company": "삼양식품", "stock_code": "003230", "relation_type": "manufacturer",
         "strength": "direct", "reason": "불닭 브랜드 제품의 제조·판매 주체",
         "evidence_kind": "company_official_product", "evidence_url": "https://www.samyangfoods.com/"},
    ],
    "오징어 게임": [
        {"company": "넷플릭스", "stock_code": None, "relation_type": "official_distributor",
         "strength": "direct", "reason": "오징어 게임의 공식 공개·유통 플랫폼",
         "evidence_kind": "official_content_page", "evidence_url": "https://www.netflix.com/title/81040344"},
        {"company": "쇼박스", "stock_code": "086980", "relation_type": "weak_market_association",
         "strength": "excluded", "reason": "공식 제작·배급 관계 확인 전에는 국내 콘텐츠주라는 이유만으로 연결하지 않음",
         "evidence_kind": "exclusion_rule", "evidence_url": None},
    ],
    "말복": [
        {"company": "하림", "stock_code": "136480", "relation_type": "ingredient_product_exposure",
         "strength": "indirect", "reason": "닭고기·삼계탕 제품군과 계절 소비의 사업 연관 후보",
         "evidence_kind": "official_product_and_dart_pending", "evidence_url": "https://www.harim.com/"},
        {"company": "마니커", "stock_code": "027740", "relation_type": "manufacturer",
         "strength": "direct", "reason": "공식 제품군에 삼계탕·백숙용 닭과 가공 삼계탕을 보유한 제조 사업자",
         "evidence_kind": "company_official_product", "evidence_url": "https://www.maniker.co.kr/m425.php"},
        {"company": "교촌에프앤비", "stock_code": "339770", "relation_type": "sector_watch",
         "strength": "sector_watch", "reason": "복날 외식 수요 관찰 대상이나 삼계탕 직접 관계는 아님",
         "evidence_kind": "sector_watch_only", "evidence_url": None},
    ],
    "두바이 초콜릿": [
        {"company": "롯데웰푸드", "stock_code": "280360", "relation_type": "product_category_watch",
         "strength": "sector_watch", "reason": "초콜릿·제과 카테고리 노출 후보이며 해당 유행 제품의 직접 제조 관계는 별도 검증 필요",
         "evidence_kind": "official_and_dart_pending", "evidence_url": "https://www.lottewellfood.com/"},
        {"company": "오리온", "stock_code": "271560", "relation_type": "product_category_watch",
         "strength": "sector_watch", "reason": "초콜릿 가공·제과 연구 역량을 가진 카테고리 관찰기업이며 두바이 초콜릿 직접 제품 관계는 미확인",
         "evidence_kind": "company_official_brochure", "evidence_url": "https://www.orionworld.com/"},
    ],
    "야구 직관": [
        {"company": "이마트", "stock_code": "139480", "relation_type": "venue_operator",
         "strength": "direct", "reason": "공식 계열사 현황에서 신세계야구단 지분 100%가 확인되는 구단 운영 연결",
         "evidence_kind": "company_official_subsidiary", "evidence_url": "https://company.emart.com/ko/investor/subsidiary.do"},
        {"company": "F&F", "stock_code": "383220", "relation_type": "merchandise_apparel",
         "strength": "sector_watch", "reason": "야구 문화 기반 패션·굿즈 소비의 카테고리 관찰기업이며 특정 KBO 구단 유니폼 계약은 별도 확인 필요",
         "evidence_kind": "category_exposure_pending", "evidence_url": "https://www.fnf.co.kr/"},
        {"company": "GS리테일", "stock_code": "007070", "relation_type": "venue_food_retail",
         "strength": "sector_watch", "reason": "직관 전후 간편식·음료 소비 접점 관찰기업이며 특정 경기장 매출·입점 관계는 미확인",
         "evidence_kind": "consumer_path_hypothesis", "evidence_url": None},
    ],
    "성수 팝업": [
        {"company": "현대백화점", "stock_code": "069960", "relation_type": "retail_space_watch",
         "strength": "sector_watch", "reason": "팝업스토어 운영 역량 관련 관찰 후보이며 특정 성수 팝업과의 직접 관계는 증거 필요",
         "evidence_kind": "official_and_dart_pending", "evidence_url": "https://www.ehyundai.com/"},
    ],
    "AI 가상 피팅": [
        {"company": "네이버", "stock_code": "035420", "relation_type": "technology_service_watch",
         "strength": "sector_watch", "reason": "커머스·AI 기술 적용 가능성 관찰 대상이며 해당 트렌드 직접 제공 관계는 검증 전",
         "evidence_kind": "official_and_dart_pending", "evidence_url": "https://www.navercorp.com/"},
    ],
    "폴더블폰": [
        {"company": "삼성전자", "stock_code": "005930", "relation_type": "manufacturer",
         "strength": "direct", "reason": "갤럭시 Z 폴더블 제품의 공식 제조·판매 주체",
         "evidence_kind": "company_official_product", "evidence_url": "https://www.samsung.com/sec/smartphones/galaxy-z/"},
    ],
    "지드래곤": [
        {"company": "갤럭시코퍼레이션", "stock_code": None, "relation_type": "artist_agency",
         "strength": "direct", "reason": "아티스트 지드래곤의 소속사로 확인되는 직접 관계",
         "evidence_kind": "company_official_artist", "evidence_url": "https://galaxyuniverse.ai/"},
    ],
    "롤 패치 노트": [
        {"company": "텐센트", "stock_code": None, "relation_type": "parent_company",
         "strength": "indirect", "reason": "리그 오브 레전드 개발사 Riot Games의 모회사 관계",
         "evidence_kind": "company_official_ownership", "evidence_url": "https://www.riotgames.com/"},
    ],
    "JIN LIGHTS UP CHARM CITY": [
        {"company": "하이브", "stock_code": "352820", "relation_type": "artist_label_group",
         "strength": "direct", "reason": "BTS 진의 소속 레이블 그룹과 직접 연결",
         "evidence_kind": "company_official_artist", "evidence_url": "https://hybecorp.com/"},
    ],
    "#JIN_IN_BALTIMORE_D2": [
        {"company": "하이브", "stock_code": "352820", "relation_type": "artist_label_group",
         "strength": "direct", "reason": "BTS 진 공연 해시태그와 소속 레이블 그룹의 직접 관계",
         "evidence_kind": "company_official_artist", "evidence_url": "https://hybecorp.com/"},
    ],
    "진": [
        {"company": "하이브", "stock_code": "352820", "relation_type": "artist_label_group",
         "strength": "direct", "reason": "BTS 진 공연 현상과 소속 레이블 그룹의 직접 관계",
         "evidence_kind": "company_official_artist", "evidence_url": "https://hybecorp.com/"},
    ],
    "nct 시온": [
        {"company": "에스엠", "stock_code": "041510", "relation_type": "artist_agency",
         "strength": "direct", "reason": "NCT WISH 시온의 소속사와 직접 연결",
         "evidence_kind": "company_official_artist", "evidence_url": "https://www.smentertainment.com/"},
    ],
}

KEYWORD_REGISTRY = {
    "말복": ["삼계탕", "보양식", "복날 외식", "삼계탕 할인", "복날 예약"],
    "불닭": ["불닭볶음면", "불닭 소스", "불닭 챌린지", "까르보불닭", "삼양식품"],
    "두바이 초콜릿": ["두쫀쿠", "피스타치오", "카다이프", "두바이 초콜릿 만들기", "초콜릿 디저트"],
    "오징어 게임": ["오징어 게임 시즌", "넷플릭스", "오징어 게임 출연진", "달고나", "오징어 게임 굿즈"],
    "리센느": ["리센느 신곡", "리센느 무대", "리센느 챌린지", "리센느 멤버", "리센느 직캠"],
    "성수 팝업": ["성수동 팝업", "팝업 예약", "성수 데이트", "브랜드 팝업", "팝업 굿즈"],
    "말차 디저트": ["말차 라떼", "말차 케이크", "말차 초콜릿", "말차 카페", "말차 레시피"],
    "러닝크루": ["러닝 모임", "러닝화", "한강 러닝", "러닝 코스", "러닝 앱"],
    "저속노화": ["저속노화 식단", "잡곡밥", "건강 식단", "혈당 관리", "저속노화 레시피"],
    "AI 가상 피팅": ["가상 착용", "AI 쇼핑", "온라인 피팅", "패션 AI", "가상 피팅 앱"],
    "여름 정주행": ["여름 드라마", "정주행 추천", "OTT 신작", "여름 영화", "휴가 콘텐츠"],
    "캐릭터 키링": ["키링 꾸미기", "가방 꾸미기", "캐릭터 굿즈", "인형 키링", "키링 팝업"],
    "야구 직관": ["프로야구 예매", "야구장 먹거리", "응원가", "유니폼", "야구장 데이트"],
    "홈카페": ["홈카페 레시피", "커피 머신", "말차 라떼", "홈카페 용품", "디저트 만들기"],
    "폴더블폰": ["갤럭시 Z", "폴드", "플립", "폴더블 비교", "폴더블 사전예약"],
    "꾸미기 챌린지": ["폰꾸", "다꾸", "가방 꾸미기", "꾸미기 영상", "꾸미기 밈"],
    "JIN LIGHTS UP CHARM CITY": ["#JIN_IN_BALTIMORE_D2", "볼티모어", "JIN", "BTS 진", "진 콘서트"],
    "#JIN_IN_BALTIMORE_D2": ["JIN LIGHTS UP CHARM CITY", "볼티모어", "JIN", "BTS 진", "진 콘서트"],
    "진": ["#JIN_IN_BALTIMORE_D2", "JIN LIGHTS UP CHARM CITY", "볼티모어", "BTS 진", "진 콘서트"],
    "nct 시온": ["NCT WISH", "시온", "NCT", "아이돌", "K-pop"],
    "롤 패치 노트": ["리그 오브 레전드", "롤 업데이트", "라이엇 게임즈", "챔피언 패치", "LoL"],
    "쿠우쿠우": ["초밥 뷔페", "쿠우쿠우 가격", "쿠우쿠우 지점", "뷔페", "외식"],
    "테니스": ["테니스 라켓", "테니스화", "테니스 레슨", "테니스 대회", "테니스 동호회"],
    "지드래곤": ["지드래곤 공연", "지드래곤 패션", "지드래곤 신곡", "GD", "갤럭시코퍼레이션"],
    "IKEONIC": ["iKON", "아이코닉", "iKON 콘서트", "iKON 월드투어", "K-pop 팬덤"],
    "유리동물원": ["유리동물원 연극", "서울연극제", "공연 예매", "테네시 윌리엄스", "연극 리뷰"],
    "이치카 생일": ["이치카", "프로젝트 세카이", "생일 이벤트", "캐릭터 굿즈", "팬아트"],
    "블루레이": ["블루레이 예약", "한정판", "영상 굿즈", "콘서트 블루레이", "블루레이 플레이어"],
    "코난 극장판": ["명탐정 코난", "코난 영화", "극장판 예매", "애니메이션 영화", "코난 굿즈"],
}

COMPANY_ROLE_META = {
    "listed_company_itself": ("직접 기업", "core"),
    "manufacturer": ("제조", "core"),
    "official_distributor": ("플랫폼·채널", "core"),
    "ingredient_product_exposure": ("원재료·부품", "value_chain"),
    "product_category_watch": ("브랜드·IP", "adjacent"),
    "retail_space_watch": ("공간·운영", "adjacent"),
    "technology_service_watch": ("인프라·서비스", "adjacent"),
    "artist_agency": ("브랜드·IP", "core"),
    "artist_label_group": ("브랜드·IP", "core"),
    "parent_company": ("브랜드·IP", "value_chain"),
    "sector_watch": ("유통·리테일", "adjacent"),
    "merchandise_apparel": ("굿즈·패션", "value_chain"),
    "venue_operator": ("공간·운영", "value_chain"),
    "venue_food_retail": ("현장 소비", "adjacent"),
    "media_broadcast": ("플랫폼·채널", "value_chain"),
    "sponsor_collaboration": ("스폰서·협업", "adjacent"),
    "weak_market_association": ("검증 제외", "excluded"),
}

RELATION_HORIZON = {
    "direct": "현재 직접 연결",
    "indirect": "현재 가치사슬 연결",
    "sector_watch": "확장 기회 관찰",
    "excluded": "연결 제외",
}

RELATION_TIER_LABEL = {
    "core": "핵심 사업자",
    "value_chain": "가치사슬 기업",
    "adjacent": "확장 관찰기업",
    "excluded": "연결 제외",
}


def canonical_topic(raw: str) -> str:
    compact = " ".join(raw.strip().split())
    legacy = ALIASES.get(compact, compact)
    return resolve_event(legacy, set())["canonical"]


def _category(topic: str) -> str:
    if topic == "말복":
        return "seasonal_food_ritual"
    if topic == "진":
        return "music_performance"
    explicit = CATEGORY_BY_TERM.get(topic)
    if explicit:
        return explicit
    lowered = topic.casefold()
    heuristic_categories = (
        (("밥", "초밥", "치킨", "라면", "빵", "커피", "맛집", "음식", "삼계탕", "디저트"), "food_culinary"),
        (("영화", "드라마", "예능", "웹툰", "애니", "극장", "방송", "집"), "screen_content"),
        (("콘서트", "앨범", "노래", "뮤직", "아이돌", "생일"), "music_performance"),
        (("야구", "축구", "테니스", "농구", "경기", "선수"), "sports_participation"),
        (("게임", "패치", "롤 ", "오버워치", "스팀"), "gaming_digital"),
        (("패션", "유니폼", "가방", "신발", "화장품"), "fashion_collectible"),
        (("여행", "호텔", "축제", "팝업", "전시"), "place_experience"),
        (("주식", "증시", "코스피", "코스닥", "채권", "금리"), "investment_market"),
    )
    for markers, category in heuristic_categories:
        if any(marker in lowered for marker in markers):
            return category
    return "unclassified"


def _series_rows(start: datetime, end: datetime, path: Path | None = None, *, observed_only: bool = False) -> list[sqlite3.Row]:
    with connect(path) as connection:
        provenance_clause = " AND provenance='observed'" if observed_only else " AND provenance='generated'"
        return connection.execute(
            f"""SELECT observed_at,source,topic,source_rank,value,provenance
               FROM hourly_observations WHERE observed_at BETWEEN ? AND ?{provenance_clause}
               ORDER BY observed_at,source,source_rank""",
            (floor_hour(start).isoformat(), floor_hour(end).isoformat()),
        ).fetchall()


def build_intelligence(at: datetime, *, hours: int = 24, path: Path | None = None) -> dict:
    end = floor_hour(at)
    start = end - timedelta(hours=max(1, hours) - 1)
    demo = BACKFILL_START <= end <= BACKFILL_END
    if not demo:
        start = max(start, BACKFILL_END + timedelta(hours=1))
    rows = _series_rows(start, end, path, observed_only=not demo)
    if demo and not rows:
        cursor = start
        rows = []
        while cursor <= end:
            rows.extend({
                "observed_at": row.observed_at, "source": row.source, "topic": row.topic,
                "source_rank": row.source_rank, "value": row.value,
                "provenance": row.provenance,
            } for row in generated_hour(cursor))
            cursor += timedelta(hours=1)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        item["canonical_topic"] = canonical_topic(item["topic"])
        grouped[item["canonical_topic"]].append(item)

    candidates = []
    company_reviews = load_company_review_overrides()
    for topic, observations in grouped.items():
        observations.sort(key=lambda item: (item["observed_at"], item["source"], item["source_rank"]))
        sources = {item["source"] for item in observations}
        event_resolution = resolve_event(topic, sources)
        observed_term_sources: dict[str, set[str]] = defaultdict(set)
        for item in observations:
            if item["provenance"] == "observed":
                observed_term_sources[item["topic"].casefold()].add(item["source"])
        observed_hours = len({item["observed_at"] for item in observations})
        latest_by_source = {}
        history_by_source: dict[str, list[dict]] = defaultdict(list)
        for item in observations:
            current = latest_by_source.get(item["source"])
            if (current is None or item["observed_at"] > current["observed_at"] or
                    (item["observed_at"] == current["observed_at"] and item["source_rank"] < current["source_rank"])):
                latest_by_source[item["source"]] = item
            history_by_source[item["source"]].append(item)
        rrf = sum(1 / (60 + item["source_rank"]) for item in latest_by_source.values())
        first_values = [item["value"] for item in observations[:max(1, len(observations)//4)]]
        last_values = [item["value"] for item in observations[-max(1, len(observations)//4):]]
        first_avg, last_avg = sum(first_values)/len(first_values), sum(last_values)/len(last_values)
        momentum = max(-1.0, min(1.0, (last_avg - first_avg) / max(first_avg, 1)))
        persistence = min(observed_hours / max(hours, 1), 1.0)
        cross = 1.0 if len(sources) >= 2 else 0.0
        rank_changes = {}
        for source, history in history_by_source.items():
            best_rank_by_time = {}
            for item in history:
                stamp = item["observed_at"]
                best_rank_by_time[stamp] = min(best_rank_by_time.get(stamp, item["source_rank"]), item["source_rank"])
            ranked_times = sorted(best_rank_by_time)
            if len(ranked_times) >= 2:
                # Positive means the item moved upward (for example 8th -> 3rd is +5).
                rank_changes[source] = best_rank_by_time[ranked_times[-2]] - best_rank_by_time[ranked_times[-1]]
            else:
                rank_changes[source] = None
        first_seen = observations[0]["observed_at"]
        last_seen = observations[-1]["observed_at"]
        first_seen_dt = datetime.fromisoformat(first_seen)
        last_seen_dt = datetime.fromisoformat(last_seen)
        is_current = last_seen_dt == end
        age_hours = max(0, int((end - first_seen_dt).total_seconds() // 3600))
        best_change = max((value for value in rank_changes.values() if value is not None), default=0)
        observed_times = sorted({datetime.fromisoformat(item["observed_at"]) for item in observations})
        max_gap_hours = max(
            ((later - earlier).total_seconds() / 3600 for earlier, later in zip(observed_times, observed_times[1:])),
            default=0,
        )
        if not is_current:
            lifecycle, lifecycle_reason = "cooling", "현재 시간에는 보이지 않아 둔화·이탈 관찰 중"
        elif age_hours <= 2:
            lifecycle, lifecycle_reason = "new", "최근 3시간 안에 처음 포착"
        elif max_gap_hours >= 24:
            lifecycle, lifecycle_reason = "rebounding", "24시간 이상 관측 공백 뒤 다시 포착"
        elif momentum >= 0.12 or best_change >= 3:
            lifecycle, lifecycle_reason = "rising", "관심 지표 또는 플랫폼 순위가 뚜렷하게 상승"
        elif len(sources) >= 2 and persistence >= 0.35:
            lifecycle, lifecycle_reason = "mainstream", "X와 Google에서 반복 관측되어 대중 확산 확인"
        else:
            lifecycle, lifecycle_reason = "sustained", "여러 시간 반복 관측되어 지속성 확인"
        score = 0.60 * min(rrf / (2/61), 1) + 0.20 * ((momentum + 1)/2) + 0.15*persistence + 0.05*cross
        raw_term = observations[-1]["topic"]
        lane, reason = observed_lane(raw_term, observed_hours=observed_hours, source_count=len(sources))
        if topic == "말복":
            lane, reason = "main", "원천 대표어는 말복으로 유지하고 소비 현상은 별도 설명"
        legacy_phenomenon_summary = {
            "말복": "말복을 앞두고 삼계탕·보양식·외식 관심이 증가",
            "진": "진의 볼티모어 공연 관련 해시태그와 팬덤 검색이 확산",
        }.get(topic)
        phenomenon_summary = event_resolution["phenomenon_summary"]
        if legacy_phenomenon_summary and event_resolution["context_status"] == "unresolved":
            phenomenon_summary = legacy_phenomenon_summary
        detected_category = event_resolution["category"] or _category(topic)
        score_calibration = 0.70 if lane == "issue" else 0.82 if detected_category == "unclassified" else 1.0
        score *= score_calibration
        keyword_items = []
        is_reconstructed = any(item["provenance"] == "generated" for item in observations)
        if is_reconstructed:
            data_confidence = {"level": "reconstructed", "label": "재구성 데모",
                               "reason": "실제 과거 검색량이 아닌 결정론적 시연 데이터"}
        elif len(sources) >= 2 and observed_hours >= 6:
            data_confidence = {"level": "high", "label": "높음",
                               "reason": "양 플랫폼과 6개 이상 시간대에서 관찰"}
        elif len(sources) >= 2:
            data_confidence = {"level": "medium", "label": "보통",
                               "reason": "X와 Google에서 교차 관찰"}
        elif observed_hours >= 2:
            data_confidence = {"level": "single_source_repeated", "label": "단일출처 반복",
                               "reason": f"한 플랫폼에서 {observed_hours}개 시간대 관찰—교차검증 전"}
        else:
            data_confidence = {"level": "low", "label": "초기 관찰",
                               "reason": "아직 한 플랫폼·한 시간대 관찰이라 지속성 검증 필요"}
        keyword_candidates = list(dict.fromkeys(
            list(KEYWORD_REGISTRY.get(topic, [])) + event_resolution["keyword_candidates"]
        ))[:5]
        for keyword in keyword_candidates:
            observed_sources = sorted(observed_term_sources.get(keyword.casefold(), set()))
            if is_reconstructed:
                keyword_items.append({"text": keyword, "source": ["reconstructed_demo"],
                                      "status": "reconstructed_demo"})
            elif observed_sources:
                keyword_items.append({"text": keyword, "source": observed_sources,
                                      "status": "observed_source_expression"})
            else:
                keyword_items.append({"text": keyword, "source": [],
                                      "status": "operator_candidate_not_rank_evidence"})
        companies = [
            {**company,
             "company_role": COMPANY_ROLE_META.get(company["relation_type"], ("기타", "adjacent"))[0],
             "relation_tier": COMPANY_ROLE_META.get(company["relation_type"], ("기타", "adjacent"))[1],
             "relation_tier_label": RELATION_TIER_LABEL[COMPANY_ROLE_META.get(company["relation_type"], ("기타", "adjacent"))[1]],
             **_company_display_state(company),
             "relation_horizon": RELATION_HORIZON.get(company["strength"], "확장 기회 관찰"),
             "exposure_status": (
                 "high_relevance" if company["strength"] == "direct"
                 else "limited_market_reflection" if company["strength"] == "indirect"
                 else "watch_candidate"
             ),
             "investment_warning": "관계 분류는 주가 상승 예측이나 매수 추천이 아님"}
            for company in COMPANY_REGISTRY.get(topic, [])
        ]
        sensitive_context = any(is_sensitive_context(item["topic"]) for item in observations)
        classified_business_context = detected_category != "unclassified" or topic in COMPANY_REGISTRY
        if detected_category == "investment_market" and topic not in COMPANY_REGISTRY:
            # A generic market term (for example, 관리종목) does not identify a
            # beneficiary. Attaching unrelated consumer companies only to meet
            # a category quota would be a false investment claim.
            classified_business_context = False
        context_resolved = event_resolution["context_status"] not in {
            "unresolved", "needs_context", "ambiguous_person"
        }
        # Live names/phrases whose meaning is still uncertain must not receive
        # generic theme-stock candidates. Curated registries and explicitly
        # labelled reconstructed demos retain their reviewed mappings.
        company_eligible = (
            lane != "issue"
            and not sensitive_context
            and classified_business_context
            and (context_resolved or topic in COMPANY_REGISTRY or is_reconstructed)
        )
        if company_eligible and detected_category == "investment_market":
            for company in companies:
                company["relation_category"] = "직접 기업·종목"
                company["value_chain_stage"] = "core"
            company_categories = [{
                "name": "직접 기업·종목",
                "value_chain_stage": "core",
                "companies": [company["company"] for company in companies],
                "candidate_count": len(companies),
                "policy": "검색어가 직접 지칭하는 상장기업만 표시",
            }]
        elif company_eligible:
            company_categories, companies = expand_value_chain(topic, detected_category, companies)
        else:
            company_categories, companies = [], []
        companies = [{**company, **relation_display(company, company_reviews)} for company in companies]
        company_resolution = {
            "status": "mapped" if companies else "excluded_by_context" if not company_eligible else "no_verified_relation",
            "mapped_count": len(companies),
            "direct_count": sum(company["strength"] == "direct" for company in companies),
            "role_coverage": sorted({company["company_role"] for company in companies}),
            "tier_counts": {tier: sum(company["relation_tier"] == tier for company in companies)
                            for tier in ("core", "value_chain", "adjacent", "excluded")},
            "category_count": len(company_categories),
            "minimum_category_requirement": 3,
            "minimum_category_met": len(company_categories) >= 3 and all(category["candidate_count"] >= 1 for category in company_categories),
            "reason": ("공식 사업관계 또는 명시적 관찰 근거가 있는 후보만 표시"
                       if companies else "사건·정책·논란 맥락은 기업 연결을 공개하지 않음"
                       if not company_eligible else "현재 근거로 검증 가능한 기업 관계가 없어 억지 테마주 연결을 보류"),
        }
        candidates.append({
            "topic": topic, "display_name": event_resolution["canonical"],
            "raw_terms": sorted({item["topic"] for item in observations}),
            "phenomenon_summary": phenomenon_summary,
            "context_status": event_resolution["context_status"],
            "ground_truth_match": event_resolution["ground_truth_match"],
            "category": detected_category, "lane": lane, "selection_reason": reason,
            "score_calibration": score_calibration,
            "company_eligible": company_eligible,
            "score": round(score*100, 2), "rrf": round(rrf*1000, 4),
            "momentum": round(momentum, 4), "persistence": round(persistence, 4),
            "score_components": {
                "rrf_points": round(60 * min(rrf / (2/61), 1), 2),
                "momentum_points": round(20 * ((momentum + 1) / 2), 2),
                "persistence_points": round(15 * persistence, 2),
                "cross_source_points": round(5 * cross, 2),
                "calibration": score_calibration,
            },
            "source_count": len(sources),
            "source_badge": "교차출처" if len(sources) >= 2 else "단일출처",
            "latest_source_ranks": {source: item["source_rank"] for source,item in latest_by_source.items()},
            "rank_change_by_source": rank_changes,
            "first_seen_at": first_seen, "last_seen_at": last_seen, "age_hours": age_hours,
            "lifecycle": lifecycle, "lifecycle_reason": lifecycle_reason,
            "data_confidence": data_confidence,
            "provenance": sorted({item["provenance"] for item in observations}),
            "series": [{"at": item["observed_at"], "source": item["source"],
                        "rank": item["source_rank"], "value": item["value"],
                        "provenance": item["provenance"]} for item in observations],
            "keywords": keyword_items,
            "keyword_evidence": {
                "total": len(keyword_items),
                "observed_source_count": sum(item["status"] == "observed_source_expression" for item in keyword_items),
                "candidate_count": sum(item["status"] == "operator_candidate_not_rank_evidence" for item in keyword_items),
                "status": "observed" if any(item["status"] == "observed_source_expression" for item in keyword_items) else "insufficient",
                "reason": ("관측 원문에서 반복된 관련 표현을 확인"
                           if any(item["status"] == "observed_source_expression" for item in keyword_items)
                           else "반복 관측된 관련어가 없어 공개 키워드는 비워 둠" if keyword_items
                           else "관련어 원문·후보 사전이 없어 키워드를 확정하지 못함"),
            },
            "companies": companies,
            "company_categories": company_categories,
            "company_resolution": company_resolution,
        })
    candidates.sort(key=lambda item: (-item["score"], item["topic"]))
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank
        item["classification"] = "이슈·주의" if item["lane"] == "issue" else "일반 트렌드" if item["company_eligible"] else "맥락 확인"
    by_persistence = sorted(candidates, key=lambda item: (-item["age_hours"], -item["persistence"], -item["score"], item["topic"]))
    by_momentum = sorted(candidates, key=lambda item: (-item["momentum"], -item["score"], item["topic"]))
    for rank, item in enumerate(by_persistence, 1):
        item["persistence_rank"] = rank
    for rank, item in enumerate(by_momentum, 1):
        item["momentum_rank"] = rank
    lanes = {name: [] for name in ("main", "issue", "review")}
    for item in candidates:
        lanes[item["lane"]].append(item)
    for lane in lanes.values():
        lane.sort(key=lambda item: item["rank"])
    evaluation_rows = []
    for item in candidates:
        expected = GROUND_TRUTH.get(item["topic"])
        if expected:
            evaluation_rows.append({
                "display_name": item["display_name"],
                "category": item["category"],
                "ground_truth_expected": {"display_name": expected[0], "category": expected[1]},
            })
    resolved_public_candidates = [
        item for item in candidates
        if item["lane"] == "main"
        and item["category"] != "unclassified"
        and (
            item["context_status"] not in {"unresolved", "needs_context", "ambiguous_person"}
            or item["topic"] in COMPANY_REGISTRY
        )
    ]
    # Preserve the source-derived score order. Unresolved but non-sensitive
    # topics stay visible with an explicit review badge and no company mapping;
    # otherwise a normal live hour can misleadingly render an empty chart.
    home_candidates = [item for item in candidates if item["lane"] != "issue"]
    for item in home_candidates:
        item["home_context_status"] = (
            "resolved" if item in resolved_public_candidates else "review_required"
        )
    public_top10 = home_candidates[:10]

    snapshot_quality = {}
    for source in ("x", "google_trends"):
        by_time = defaultdict(list)
        for row in rows:
            if row["source"] == source and row["provenance"] == "observed":
                by_time[row["observed_at"]].append((row["source_rank"], row["topic"]))
        fingerprints = [tuple(sorted(values)) for _, values in sorted(by_time.items())]
        top_sets = [
            {topic for rank, topic in values if rank <= 10}
            for _, values in sorted(by_time.items())
        ]
        unique_count = len(set(fingerprints))
        consecutive_unchanged = sum(
            left == right for left, right in zip(fingerprints, fingerprints[1:])
        )
        top10_overlaps = [
            len(left & right) / max(len(left | right), 1)
            for left, right in zip(top_sets, top_sets[1:])
        ]
        average_top10_overlap = (
            sum(top10_overlaps) / len(top10_overlaps) if top10_overlaps else 0.0
        )
        snapshot_quality[source] = {
            "snapshot_count": len(fingerprints),
            "unique_snapshot_count": unique_count,
            "consecutive_unchanged_count": consecutive_unchanged,
            "unchanged_rate": round(consecutive_unchanged / max(len(fingerprints) - 1, 1), 4),
            "average_top10_overlap": round(average_top10_overlap, 4),
            "status": (
                "insufficient_history" if len(fingerprints) < 3
                else "stale_or_static_feed" if consecutive_unchanged == len(fingerprints) - 1
                else "low_churn_needs_source_review" if average_top10_overlap >= 0.9
                else "changing"
            ),
        }
    return {
        "mode": "reconstructed_demo" if demo else "live",
        "is_live": not demo,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "hours": hours},
        "sources": ["x", "google_trends"],
        "score_formula": "60% source-rank RRF + 20% momentum + 15% persistence + 5% cross-source",
        "normalization_evaluation": evaluate_resolution(evaluation_rows),
        "unified_ranking": candidates,
        "public_top10": public_top10,
        "quality_summary": {
            "total_ranked_candidates": len(candidates),
            "main_candidates": len(lanes["main"]),
            "public_eligible_candidates": len(home_candidates),
            "resolved_public_candidates": len(resolved_public_candidates),
            "review_required_in_public_top10": sum(
                item["home_context_status"] == "review_required" for item in public_top10
            ),
            "public_top10_count": len(public_top10),
            "excluded_from_public_due_to_issue_lane": len(candidates) - len(home_candidates),
            "top10_with_five_keywords": sum(
                sum(keyword["status"] == "observed_source_expression" for keyword in item["keywords"]) == 5
                for item in public_top10
            ),
            "top10_with_company_mapping": sum(bool(item["companies"]) for item in public_top10),
            "top10_without_forced_company": sum(not item["companies"] for item in public_top10),
            "top10_low_confidence": sum(item["data_confidence"]["level"] == "low" for item in public_top10),
            "source_snapshot_quality": snapshot_quality,
        },
        "lanes": lanes,
    }
