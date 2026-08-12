from __future__ import annotations

from collections.abc import Iterable


POLICY_VERSION = "trend-fit-v1"

# These signals decide where an already observed X/Google item is presented.
# They never alter the source-derived ranking score.
HARD_ISSUE_MARKERS = {
    "정치", "대통령", "국회", "정당", "선거", "탄핵", "장관", "국방부",
    "전쟁", "미사일", "테러", "사망", "살인", "폭행", "범죄", "구속",
    "혐의", "고소", "경찰서", "재난", "지진", "산불", "태풍", "폭염경보",
    "사생활", "불륜", "스토커", "논란", "친일", "장학금",
    "배상", "판결", "소송", "재판", "기소", "유죄", "대법원", "법원",
}

HARD_ISSUE_CATEGORIES = {
    "policy_issue", "politics", "incident", "crime", "disaster", "weather_alert",
    "privacy_controversy",
}

TREND_CATEGORIES = {
    "food_culinary",
    "seasonal_food_ritual",
    "music_performance",
    "screen_content",
    "gaming_digital",
    "sports_attendance",
    "sports_participation",
    "fashion_collectible",
    "product_brand",
    "place_experience",
    "lifestyle_behavior",
    "wellness_behavior",
    "participation_meme",
    "technology_tool",
    "investment_market",
}

NAMED_OBJECT_MARKERS = {
    "디저트", "쿠키", "초콜릿", "라면", "치킨", "커피", "음료", "메뉴", "맛집", "카페",
    "영화", "드라마", "예능", "웹툰", "애니", "극장판", "콘서트", "앨범",
    "신곡", "게임", "패치", "캐릭터", "굿즈", "키링", "유니폼", "팝업",
    "챌린지", "밈", "스마트폰", "폴더블폰", "휴대폰", "신발", "가방", "화장품", "주식",
    "코스피", "코스닥", "야구", "축구", "농구", "테니스",
}

REPEATABLE_BEHAVIOR_MARKERS = {
    "직관", "러닝", "챌린지", "꾸미기", "정주행", "먹방", "레시피",
    "후기", "예약", "관람", "방문", "여행", "콜라보", "협업", "응원",
}

CONSUMER_ACTION_MARKERS = {
    "구매", "할인", "예약", "판매", "품절", "굿즈", "메뉴", "카페",
    "편의점", "관람", "방문", "여행", "외식", "먹기", "출시",
}

PRODUCTIZATION_MARKERS = {
    "제품", "브랜드", "신메뉴", "출시", "굿즈", "메뉴", "콜라보", "협업",
    "시즌", "한정판", "편의점", "카페",
}

# Broad taxonomy words are valid raw observations, but the word alone does not
# identify a reproducible product, content, behaviour, or market phenomenon.
# Keep them in the unified ranking and ask for context instead of promoting a
# circular "category matched, therefore named object" conclusion.
GENERIC_CATEGORY_WORDS = {
    "음식", "제품", "브랜드", "콘텐츠", "생활", "문화", "기술",
}


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    compact = text.casefold().replace(" ", "")
    return any(marker.casefold().replace(" ", "") in compact for marker in markers)


def assess_trend_fit(
    term: str,
    *,
    category: str = "unclassified",
    context_terms: Iterable[str] = (),
    issue_context_terms: Iterable[str] = (),
    news_claim_types: Iterable[str] = (),
) -> dict:
    """Classify presentation fit without changing an observed item's score.

    News evidence can explain why a source-observed expression is culturally or
    commercially meaningful, but it cannot create or rank a trend by itself.
    """

    normalized_term = " ".join(str(term or "").strip().split())
    context = " ".join(
        [normalized_term, *(" ".join(str(value).strip().split()) for value in context_terms)]
    )
    issue_context_values = [
        " ".join(str(value).strip().split())
        for value in issue_context_terms
        if str(value).strip()
    ]
    issue_context = " ".join([normalized_term, *issue_context_values])
    claim_types = {str(value).strip() for value in news_claim_types if str(value).strip()}
    labels: list[str] = []

    hard_issue = (
        category in HARD_ISSUE_CATEGORIES
        or _contains_any(issue_context, HARD_ISSUE_MARKERS)
    )
    generic_category_word = normalized_term.casefold() in {
        value.casefold() for value in GENERIC_CATEGORY_WORDS
    }
    has_specific_context = any((
        _contains_any(context, NAMED_OBJECT_MARKERS),
        _contains_any(context, REPEATABLE_BEHAVIOR_MARKERS),
        _contains_any(context, CONSUMER_ACTION_MARKERS),
        _contains_any(context, PRODUCTIZATION_MARKERS),
    ))
    if (
        (category in TREND_CATEGORIES and not generic_category_word)
        or _contains_any(context, NAMED_OBJECT_MARKERS)
    ):
        labels.append("named_object")
    if _contains_any(context, REPEATABLE_BEHAVIOR_MARKERS) or "consumer_behavior" in claim_types:
        labels.append("repeatable_behavior")
    if _contains_any(context, CONSUMER_ACTION_MARKERS) or claim_types & {"sales_rank", "consumer_behavior"}:
        labels.append("consumer_action")
    if _contains_any(context, PRODUCTIZATION_MARKERS) or "product_launch" in claim_types:
        labels.append("productization")
    if len(labels) >= 2 or claim_types & {"search_growth", "cross_platform_spread"}:
        labels.append("cross_context")

    labels = list(dict.fromkeys(labels))
    short_or_generic = len(normalized_term.replace(" ", "")) <= 2
    ambiguous = (
        not labels
        or (short_or_generic and category == "unclassified")
        or (generic_category_word and not has_specific_context)
    )

    if hard_issue:
        selection = "issue"
        reason = "정치·사건사고·재난·단순 기상특보·사생활 논란 맥락"
    elif labels and not (generic_category_word and not has_specific_context):
        selection = "main"
        reason = "제품·콘텐츠·문화·소비·생활·스포츠·기술 또는 참여 행동 신호"
    else:
        selection = "review"
        reason = "원문은 보존하되 문화·소비·행동 맥락을 아직 확인하지 못함"

    return {
        "policy_version": POLICY_VERSION,
        "selection": selection,
        "main_eligible": selection == "main",
        "hard_issue": hard_issue,
        "ambiguous": ambiguous,
        "generic_category_word": generic_category_word,
        "labels": labels,
        "reason": reason,
        "news_context_used": bool(claim_types),
        "issue_context_used": bool(issue_context_values),
        "rank_effect": "none",
    }
