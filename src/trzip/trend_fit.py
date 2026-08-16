from __future__ import annotations

from collections.abc import Iterable
import re

from .source_safety import is_spam_solicitation


POLICY_VERSION = "trend-fit-v5"

# Product-owner approved proper names are self-contained trend subjects when
# they were actually observed in X/Google.  News or company enrichment may add
# an explanation later, but it must never be a prerequisite for placing these
# titles/IP/fandom events in the main candidate lane.
REVIEWED_NAMED_TREND_TERMS = {
    "둠스데이",
    "미스터 시니스터",
    "놀토",
    "겨울왕국",
    "엑스맨",
    "베리즈 라이브",
    "세츠나하나비",
    "월즈 진출",
    "ufc 330",
    "그래미 어워드",
    "콜 오브 듀티",
    "스타파이터",
    "어것디 10주년",
    "오시온 버블",
    "재벌형사",
    "미스 인도네시아",
    "코믹월드",
    # One public-observation event may appear as a holiday name, people who
    # embody it, a commemoration phrase, or a translated hashtag.  These are
    # concrete observed trend subjects, not generic political keywords.
    "#광복절",
    "광복절",
    "광복",
    "독립",
    "독립운동가",
    "독립유공자",
    "순국선열",
    "#대한독립만세",
    "대한독립만세",
    "대한민국 광복절",
    "대한민국 광복절 주년",
    "광복절 태극기",
    "#koreanliberationday",
    "south korea national liberation day",
}

SPORTS_DISCIPLINE_TERMS = {
    "football": {
        "밀란", "맨유", "man united", "man utd", "수원fc", "수원 fc",
        "제주", "안양", "fc 서울", "대전", "마르세유", "아틀레티코",
        "스토크 시티", "스완지 시티",
    },
    "baseball": {
        "한화", "삼성", "두산", "kia", "ssg", "lg", "키움", "kt",
        "nc", "롯데", "다이아몬드백스", "브레이브스", "브루어스", "다저스",
    },
    "basketball": {"농구", "basketball"},
    "cricket": {
        "ind", "india", "sl", "sri lanka", "australia", "bangladesh",
        "인도", "스리랑카", "호주", "방글라데시",
    },
}


def sports_discipline_for_name(term: str) -> str | None:
    """Return a stable sport bucket for one actually observed fixture."""

    normalized = " ".join(str(term or "").casefold().split())
    if not re.search(r"\S+\s+(?:대|vs\.?|v\.?)\s+\S+", normalized) and "한일전" not in normalized:
        return None
    for discipline, markers in SPORTS_DISCIPLINE_TERMS.items():
        if any(
            bool(re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", normalized))
            if marker.isascii()
            else marker in normalized
            for marker in markers
        ):
            return discipline
    return "other_sport"

# These signals decide where an already observed X/Google item is presented.
# They never alter the source-derived ranking score.
HARD_ISSUE_MARKERS = {
    "정치", "대통령", "국회", "정당", "선거", "탄핵", "장관", "국방부",
    "전쟁", "미사일", "테러", "사망", "살인", "폭행", "범죄", "구속",
    "혐의", "고소", "체포", "경찰서", "재난", "지진", "산불", "태풍", "폭염경보",
    "사생활", "불륜", "스토커", "논란", "친일", "장학금",
    "배상", "판결", "소송", "재판", "기소", "유죄", "대법원", "법원", "지원금",
}

# A single secondary-platform title containing one of these words is not
# sufficient to classify the whole observed trend as a controversy.  The
# observed term itself may still be an issue, while provider-only context needs
# corroboration from at least two separate titles.
SOFT_PROVIDER_ISSUE_MARKERS = {
    "사생활", "불륜", "스토커", "논란", "친일",
}

STRONG_PROVIDER_ISSUE_MARKERS = HARD_ISSUE_MARKERS - SOFT_PROVIDER_ISSUE_MARKERS

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
    "public_observation_event",
    "technology_tool",
    "investment_market",
}

NAMED_OBJECT_MARKERS = {
    "디저트", "쿠키", "초콜릿", "라면", "치킨", "커피", "음료", "메뉴", "맛집", "카페",
    "삼계탕", "보양식", "축제", "전시", "팝업", "일식", "월식", "유성우", "별똥별",
    "영화", "드라마", "예능", "웹툰", "애니", "극장판", "콘서트", "앨범",
    "신곡", "게임", "패치", "캐릭터", "굿즈", "키링", "유니폼", "한복", "박람회", "팝업",
    "챌린지", "밈", "스마트폰", "폴더블폰", "휴대폰", "신발", "가방", "화장품", "주식",
    "코스피", "코스닥", "상장폐지", "관리종목", "증권", "가상자산", "비트코인", "cpi", "금리",
    "야구", "축구", "농구", "테니스", "로봇", "휴머노이드", "반도체", "원자로",
    "닭",
    # Reviewed product, service, IP and named-event identities.  Unlike broad
    # category nouns these expressions identify what people are looking for,
    # even when the source label itself is compact.
    "아이폰", "티빙", "지스타", "검은사막", "데이즈드", "삼전넥스", "챱챱 물개",
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
    "음식", "제품", "브랜드", "콘텐츠", "생활", "문화", "기술", "애니",
    "운전", "날씨", "여행", "스포츠", "주식", "패션", "뷰티", "음악", "영상",
    # Broad places, regions and activity/content classes are observations, not
    # self-contained product trends. A concrete venue, event, work, brand or
    # observed modifier is required before they can enter the home subset.
    "수영장", "유럽", "아시아", "예능", "특집", "특집 예능",
    "야구", "축구", "농구", "테니스",
    # A product/category class is not a self-contained trend event.  These
    # labels remain in the canonical ranking but need an observed modifier or
    # reviewed trigger before entering the product-facing main lane.
    "라면", "한복", "반도체", "삼계탕",
}

MARKET_EVENT_MARKERS = {
    "주가", "실적", "상장", "상장폐지", "공모", "배당", "인수", "합병",
    "증자", "감자", "거래정지", "관리종목", "신고가", "급등", "급락",
    "주식", "채권", "금리", "cpi", "국채", "비트코인",
}

SPORTS_EVENT_MARKERS = {
    "한일전", "결승", "준결승", "개막", "우승", "홈런", "이적", "부상",
    "기록", "직관", "예매", "중계", "경기", "대회", "플레이오프",
}

CORPORATE_ENTITY_SUFFIXES = {
    "그룹", "전자", "이노텍", "에셋", "증권", "홀딩스", "산업", "건설",
    "화학", "금융", "은행", "카드", "보험", "제약", "바이오",
}

def _has_specific_term_shape(term: str) -> bool:
    """Recognise concrete structures without consulting a reviewed term list."""

    normalized = " ".join(str(term or "").casefold().split())
    sports_fixture = bool(re.search(r"\S+\s+(?:대|vs\.?|v\.?)\s+\S+", normalized))
    seasonal_ritual = bool(re.fullmatch(r"[초중말]복", normalized))
    return sports_fixture or seasonal_ritual


def _has_specific_sports_event(term: str) -> bool:
    normalized = " ".join(str(term or "").casefold().split())
    return bool(
        re.search(r"\S+\s+(?:대|vs\.?|v\.?)\s+\S+", normalized)
        or any(marker in normalized for marker in SPORTS_EVENT_MARKERS)
    )


def _is_plain_sports_fixture(term: str, category: str) -> bool:
    """Identify a concrete fixture while preserving its product eligibility.

    A fixture names a specific event and may enter Main after normal context
    checks. This flag is informational; only broad team/sport subjects without
    a fixture or event marker remain in Review.
    """

    if category not in {"sports_attendance", "sports_participation"}:
        return False
    normalized = " ".join(str(term or "").casefold().split())
    is_fixture = bool(re.search(r"\S+\s+(?:대|vs\.?|v\.?)\s+\S+", normalized))
    event_markers = SPORTS_EVENT_MARKERS - {"경기"}
    return bool(is_fixture and not _contains_any(normalized, event_markers))


def _is_standalone_corporate_subject(term: str, category: str) -> bool:
    if category in {"sports_attendance", "sports_participation"}:
        return False
    normalized = "".join(str(term or "").casefold().split())
    if not normalized or _contains_any(normalized, MARKET_EVENT_MARKERS | SPORTS_EVENT_MARKERS):
        return False
    return any(normalized.endswith(suffix) for suffix in CORPORATE_ENTITY_SUFFIXES)


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    # Keep whitespace so a marker cannot be manufactured across two tokens
    # (for example ``보고 소원`` -> ``고소`` in the old compact matcher).
    normalized = " ".join(str(text or "").casefold().split())
    return any(
        " ".join(marker.casefold().split()) in normalized
        for marker in markers
    )


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
    claim_types = {str(value).strip() for value in news_claim_types if str(value).strip()}
    labels: list[str] = []
    spam_solicitation = is_spam_solicitation(normalized_term)
    reviewed_named_trend = normalized_term.casefold() in {
        value.casefold() for value in REVIEWED_NAMED_TREND_TERMS
    }

    provider_soft_issue_matches = sum(
        _contains_any(value, SOFT_PROVIDER_ISSUE_MARKERS)
        for value in issue_context_values
    )
    hard_issue = (
        category in HARD_ISSUE_CATEGORIES
        or _contains_any(normalized_term, HARD_ISSUE_MARKERS)
        or any(
            _contains_any(value, STRONG_PROVIDER_ISSUE_MARKERS)
            for value in issue_context_values
        )
        or provider_soft_issue_matches >= 2
    )
    generic_tokens = normalized_term.casefold().split()
    generic_category_word = bool(generic_tokens) and all(
        token in {value.casefold() for value in GENERIC_CATEGORY_WORDS}
        for token in generic_tokens
    )
    standalone_market_subject = bool(
        category == "investment_market"
        and not _contains_any(normalized_term, MARKET_EVENT_MARKERS)
    )
    nonspecific_sports_subject = bool(
        category in {"sports_attendance", "sports_participation"}
        and not _has_specific_sports_event(normalized_term)
    )
    plain_sports_fixture = _is_plain_sports_fixture(normalized_term, category)
    standalone_corporate_subject = _is_standalone_corporate_subject(
        normalized_term,
        category,
    )
    has_specific_context = any((
        _contains_any(context, NAMED_OBJECT_MARKERS),
        _contains_any(context, REPEATABLE_BEHAVIOR_MARKERS),
        _contains_any(context, CONSUMER_ACTION_MARKERS),
        _contains_any(context, PRODUCTIZATION_MARKERS),
    ))
    # A category is an output label, not evidence that the raw expression is a
    # concrete trend.  Otherwise a broad word such as "운전" can become
    # screen_content through one related query and then circularly promote
    # itself.  Promotion requires a lexical/structural signal in observed data.
    if (
        _contains_any(context, NAMED_OBJECT_MARKERS)
        or _has_specific_term_shape(normalized_term)
        or reviewed_named_trend
        or (category == "investment_market" and _contains_any(normalized_term, MARKET_EVENT_MARKERS))
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

    if spam_solicitation:
        selection = "issue"
        reason = "광고·연락 유도·성인성 구인형 스팸 표현"
    elif hard_issue:
        selection = "issue"
        reason = "정치·사건사고·재난·단순 기상특보·사생활 논란 맥락"
    elif (
        labels
        and not generic_category_word
        and not standalone_market_subject
        and not nonspecific_sports_subject
        and not standalone_corporate_subject
    ):
        selection = "main"
        reason_parts = {
            "named_object": "구체적 대상",
            "repeatable_behavior": "반복 참여 행동",
            "consumer_action": "소비 행동",
            "productization": "제품화 신호",
            "cross_context": "교차 맥락 확산",
        }
        reason = " · ".join(reason_parts[label] for label in labels)
    else:
        selection = "review"
        reason = "원문은 보존하되 문화·소비·행동 맥락을 아직 확인하지 못함"

    return {
        "policy_version": POLICY_VERSION,
        "selection": selection,
        "main_eligible": selection == "main",
        "hard_issue": hard_issue,
        "spam_solicitation": spam_solicitation,
        "ambiguous": ambiguous,
        "generic_category_word": generic_category_word,
        "standalone_market_subject": standalone_market_subject,
        "nonspecific_sports_subject": nonspecific_sports_subject,
        "plain_sports_fixture": plain_sports_fixture,
        "reviewed_named_trend": reviewed_named_trend,
        "standalone_corporate_subject": standalone_corporate_subject,
        "labels": labels,
        "reason": reason,
        "news_context_used": bool(claim_types),
        "issue_context_used": bool(issue_context_values),
        "provider_soft_issue_match_count": provider_soft_issue_matches,
        "rank_effect": "none",
    }
