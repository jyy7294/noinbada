from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .hourly_store import generated_hour

ISSUE_TERMS = {"경기도교육청", "국가장학금", "국채", "거제경찰서", "김수키"}
PERSON_OR_RESULT_TERMS: set[str] = set()
CONTEXT_REQUIRED_TERMS = {"블루레이", "테니스", "쿠우쿠우"}
MAIN_TERMS = {"두바이 초콜릿", "불닭", "오징어 게임", "리센느", "러닝크루", "성수 팝업",
              "말차 디저트", "꾸미기 챌린지", "폴더블폰", "여름 정주행", "AI 가상 피팅",
              "야구 직관", "캐릭터 키링", "저속노화", "홈카페"}
DEMO_MAIN_POOL = ("두바이 초콜릿", "불닭", "오징어 게임", "리센느", "러닝크루",
                  "성수 팝업", "말차 디저트", "꾸미기 챌린지", "폴더블폰", "AI 가상 피팅")

EVENT_CONTEXT = {
    "말복": {"event": "말복", "summary": "말복을 앞두고 삼계탕·보양식·외식 관심이 증가", "category": "seasonal_food_ritual",
             "signals": ["삼계탕", "보양식", "외식", "할인", "예약"]},
}

CATEGORY_BY_TERM = {
    "두바이 초콜릿": "food_culinary", "불닭": "food_culinary", "말차 디저트": "food_culinary",
    "리센느": "music_performance", "오징어 게임": "screen_content",
    "성수 팝업": "place_experience", "러닝크루": "lifestyle_behavior",
    "꾸미기 챌린지": "participation_meme", "폴더블폰": "product_brand",
    "AI 가상 피팅": "technology_tool", "캐릭터 키링": "fashion_collectible",
    "저속노화": "wellness_behavior", "홈카페": "lifestyle_behavior",
    "여름 정주행": "screen_content", "야구 직관": "sports_attendance",
    # Categories induced from observed Korean X/Google snapshots. Exact entries
    # are deliberately reviewed rather than guessing from arbitrary nouns.
    "테니스": "sports_participation", "지드래곤": "music_performance",
    "롤 패치 노트": "gaming_digital", "쿠우쿠우": "food_culinary",
    "JIN LIGHTS UP CHARM CITY": "music_performance",
    "#JIN_IN_BALTIMORE_D2": "music_performance", "볼티모어": "place_experience",
    "nct 시온": "music_performance", "블루레이": "screen_content",
    "이치카 생일": "gaming_digital", "유리동물원": "screen_content",
    "IKEONIC": "music_performance", "코난 극장판": "screen_content",
}

REVIEWED_MAIN_TERMS = set(CATEGORY_BY_TERM)

CONTROVERSY_CONTEXT_MARKERS = {
    "논란", "사생활", "불륜", "스토커", "친일", "폭행", "구속", "범죄", "사망",
    "경찰서", "미사일", "국방부", "전쟁", "테러", "재난", "혐의", "고소", "피해자",
}


def is_sensitive_context(term: str) -> bool:
    compact = term.casefold().replace(" ", "")
    return any(marker.casefold().replace(" ", "") in compact for marker in CONTROVERSY_CONTEXT_MARKERS)


def lane_for_raw_term(term: str) -> tuple[str, str]:
    if is_sensitive_context(term):
        return "issue", "논란·사생활·범죄·재난 등 주의 맥락으로 기업 연결 제외"
    if term in EVENT_CONTEXT:
        return "main", "계절 키워드가 음식·구매·방문 행동 사건으로 확장됨"
    if term in ISSUE_TERMS:
        return "issue", "기관·정책·사건성 검색어"
    if term in PERSON_OR_RESULT_TERMS:
        return "main", "인물·경기 항목도 실제 관측 트렌드로 포함"
    if term in CONTEXT_REQUIRED_TERMS:
        return "review", "일반명사·브랜드 단독 표현으로 반복 또는 교차출처 확인 필요"
    if term in MAIN_TERMS or term in REVIEWED_MAIN_TERMS:
        return "main", "소비·문화·콘텐츠·제품 또는 참여 행동 맥락"
    return "main", "X·Google에서 실제 관측된 항목으로 통합 순위에 포함"


def observed_lane(term: str, *, observed_hours: int, source_count: int) -> tuple[str, str]:
    """Apply evidence gates that cannot be decided from a term alone."""
    lane, reason = lane_for_raw_term(term)
    if term in CONTEXT_REQUIRED_TERMS and (observed_hours >= 2 or source_count >= 2):
        return "main", "일반명사·브랜드이나 2개 시간대 반복 또는 X·Google 교차관찰로 관심 지속 확인"
    if lane == "review":
        return "main", "문맥 확정 전 항목도 삭제하지 않고 통합 순위에 포함"
    return lane, reason


def curate_raw_platform_items(items: list[dict]) -> dict[str, list[dict]]:
    lanes: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        lane, reason = lane_for_raw_term(item["title"])
        context = EVENT_CONTEXT.get(item["title"])
        lanes[lane].append({**item,
                            "raw_title": item["title"],
                            "title": context["event"] if context else item["title"],
                            "phenomenon_summary": context.get("summary", "") if context else "",
                            "category": context["category"] if context else CATEGORY_BY_TERM.get(item["title"], "unclassified"),
                            "context_signals": context["signals"] if context else [],
                            "lane": lane, "reason": reason})
    return {name: lanes.get(name, []) for name in ("main", "issue", "review")}


def reconstructed_demo_feed(at: datetime) -> dict:
    by_topic: dict[str, dict] = {}
    for row in generated_hour(at, seed_topics=DEMO_MAIN_POOL):
        entry = by_topic.setdefault(row.topic, {"title": row.topic, "source_ranks": {}, "score": 0.0})
        entry["source_ranks"][row.source] = row.source_rank
        entry["score"] += 1 / (60 + row.source_rank)
    ranked = sorted(by_topic.values(), key=lambda row: (-row["score"], row["title"]))
    lanes: dict[str, list[dict]] = defaultdict(list)
    for row in ranked:
        lane, reason = lane_for_raw_term(row["title"])
        row.update(lane=lane, reason=reason, score=round(row["score"] * 1000, 4))
        lanes[lane].append(row)
    for values in lanes.values():
        for rank, row in enumerate(values, 1):
            row["rank"] = rank
    return {"mode": "reconstructed_demo", "is_live": False,
            "demo_window": {"from": "2026-05-01T00:00:00+09:00", "to": "2026-08-12T11:00:00+09:00"},
            "observed_at": at.isoformat(),
            "lanes": {name: lanes.get(name, []) for name in ("main", "issue", "review")}}
