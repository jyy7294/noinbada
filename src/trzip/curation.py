from __future__ import annotations

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

CONTROVERSY_CONTEXT_MARKERS = {
    "논란", "사생활", "불륜", "스토커", "친일", "폭행", "구속", "범죄", "사망",
    "경찰서", "미사일", "국방부", "전쟁", "테러", "재난", "혐의", "고소", "피해자",
    "지진", "태풍", "폭염", "호우", "산불", "경보", "날씨",
    "대통령", "국회", "정당", "선거", "탄핵", "정부 정책",
}


def is_sensitive_context(term: str) -> bool:
    # Preserve token boundaries.  Removing whitespace made unrelated adjacent
    # words such as ``보고 소원`` look as if they contained ``고소``.
    normalized = " ".join(str(term or "").casefold().split())
    return any(
        " ".join(marker.casefold().split()) in normalized
        for marker in CONTROVERSY_CONTEXT_MARKERS
    )
