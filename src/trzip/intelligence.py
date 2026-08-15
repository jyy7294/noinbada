from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .company_roles import (
    COMPANY_ROLE_LABELS,
    PUBLIC_COMPANY_ROLE_CATEGORIES,
    public_company_role_count_is_valid,
    select_role_diverse_company_projection,
    with_company_role,
)
from .category_ontology import category_ontology
from .curation import is_sensitive_context
from .hourly_store import (
    ELIGIBLE_COLLECTOR_SQL,
    KST,
    connect,
    default_db_path,
    floor_hour,
    source_hour_quality,
)
from .value_chain import expand_value_chain
from .event_resolution import (
    GROUND_TRUTH,
    evaluate_resolution,
    normalize_event_key,
    observation_summary,
    resolve_event,
)
from .ontology import (
    DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
    MINIMUM_PUBLISHED_COMPANIES,
    MINIMUM_FRONTEND_COMPANIES,
    OntologyGraph,
)
from .provider_verification import latest_verification_by_trend
from .ranking_v2 import build_period_rankings_v2
from .presentation_feed import build_presentation_feed
from .keyword_policy import keyword_fits_public_label
from .trend_fit import assess_trend_fit
from .readiness import (
    LONG_HORIZON_HISTORY_HOURS,
    MVP_HISTORY_HOURS,
    OPERATIONAL_HISTORY_TARGET_HOURS,
    history_stage,
)


ONTOLOGY_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "ontology_seed.json"
ONTOLOGY_ENRICHMENT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ontology_enrichment.json"
)
ONTOLOGY_HUMANOID_ENRICHMENT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ontology_humanoid_enrichment.json"
)
ONTOLOGY_BRAND_ENRICHMENT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ontology_brand_enrichment.json"
)
ONTOLOGY_CULTURE_ENRICHMENT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ontology_culture_enrichment.json"
)
ONTOLOGY_ENRICHMENT_PATHS = (
    ONTOLOGY_ENRICHMENT_PATH,
    ONTOLOGY_HUMANOID_ENRICHMENT_PATH,
    ONTOLOGY_BRAND_ENRICHMENT_PATH,
    ONTOLOGY_CULTURE_ENRICHMENT_PATH,
)


 # X and Google are the only comparable rank feeds. NAVER News answers
 # "why now?"; a search-result count is not a population-attention rank and
 # is never mixed into the mathematical attention score.
HOME_SOURCE_POLICY_VERSION = "home-feed-selection-v2-x-google-only"
# NAVER 뉴스만 보조 신호로 사용한다. 블로그·검색트렌드·YouTube·Instagram은
# 수집/검증/홈 선별 입력에서 제외한다.
OPTIONAL_HOME_SOURCES: tuple[str, ...] = ()
PUBLIC_BROAD_CATEGORIES = {
    "food", "content", "sports", "lifestyle", "culture", "consumer",
    "technology", "market",
}


def _source_related_terms(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(value).strip() for value in values if str(value).strip()] if isinstance(values, list) else []


def canonical_topic(raw: str, related_terms_json: str | None = None) -> str:
    """Create the ranking key using format-only, deterministic normalization.

    Reviewed aliases and the event reference set may enrich a published item,
    but they must not merge source rows or change rank/product-fit eligibility.
    """

    normalized = normalize_event_key(raw)
    related = [normalize_event_key(value) for value in _source_related_terms(related_terms_json)]
    context = " ".join([normalized, *related])
    # Ambiguous short expressions are merged only when the source itself
    # supplies matching related-query evidence. Bare ``일식`` can also mean
    # Japanese food, so it becomes an eclipse only with eclipse context.
    if normalized in {"일식", "개기일식"} and "개기일식" in context:
        return "개기일식"
    meteor_terms = {
        "유성우", "유성우 시간", "페르세우스", "페르세우스 유성우",
        "페르세우스 유성우 시간", "별똥별", "별똥별 시간", "별똥별 보고",
        "유성우 보고",
    }
    meteor_context = any(marker in context for marker in ("페르세우스 유성우", "유성우 시간"))
    if normalized in meteor_terms and meteor_context:
        return "페르세우스 유성우"
    # Sports fixtures often arrive as search-query variants.  Strip display
    # suffixes and format-only team markers before ranking so one match cannot
    # occupy multiple positions.  This is a general linguistic rule, not a
    # manually curated trend whitelist.
    fixture = re.fullmatch(r"(.+?)\s+(?:대|vs\.?|v\.?)\s+(.+?)(?:\s+순위)?", normalized)
    if fixture:
        def normalize_team(value: str) -> str:
            team = re.sub(r"\s+fc$", "", value.strip())
            team = re.sub(r"^엘\s*에이\b", "로스앤젤레스", team)
            return " ".join(team.split())

        left, right = (normalize_team(value) for value in fixture.groups())
        return f"{left} 대 {right}"
    # Release suffixes are format variants for common macro indicators, not a
    # reviewed trend alias. Keep this deterministic family rule deliberately
    # narrow so arbitrary nouns ending in "발표" are never merged.
    match = re.fullmatch(r"(cpi|ppi|gdp|fomc)\s+(?:발표|release)", normalized)
    return match.group(1) if match else normalized


def _assign_canonical_topics(rows: list[dict]) -> list[dict]:
    """Share source context for the same expression within a 24-hour event.

    X often supplies only a bare topic while Google supplies related queries.
    This lets those two observations resolve together without using a manual
    ranking whitelist or carrying context across unrelated dates.
    """

    indexed: dict[str, list[tuple[datetime, list[str]]]] = defaultdict(list)
    for row in rows:
        key = normalize_event_key(row.get("topic") or "")
        stamp = datetime.fromisoformat(str(row["observed_at"]))
        indexed[key].append((stamp, _source_related_terms(row.get("related_terms_json"))))
    output = []
    for source in rows:
        row = dict(source)
        key = normalize_event_key(row.get("topic") or "")
        stamp = datetime.fromisoformat(str(row["observed_at"]))
        context = []
        for other_stamp, terms in indexed.get(key, []):
            if abs((stamp - other_stamp).total_seconds()) <= 24 * 3600:
                context.extend(terms)
        context_json = json.dumps(list(dict.fromkeys(context)), ensure_ascii=False)
        row["event_key"] = canonical_topic(row.get("topic") or "", context_json)
        row["canonical_topic"] = row["event_key"]
        output.append(row)
    return output


def _provider_issue_context_titles(providers: dict, representative: str) -> list[str]:
    """Keep only verification titles that explicitly name a specific trend.

    Verification search results are contextual evidence, not ranking input.
    Short generic terms are excluded because substring matches in third-party
    titles are too ambiguous to justify an issue label.
    """

    representative_compact = "".join(str(representative or "").casefold().split())
    if len(representative_compact) < 3:
        return []
    titles = []
    for provider in providers.values():
        if not provider.get("matched"):
            continue
        for evidence in provider.get("evidence") or []:
            title = str(evidence.get("title") or "").strip()
            title_compact = "".join(title.casefold().split())
            if title and representative_compact in title_compact:
                titles.append(title)
    return list(dict.fromkeys(titles))


def _category(topic: str) -> str:
    lowered = topic.casefold()
    if re.fullmatch(r"[초중말]복", lowered):
        return "seasonal_food_ritual"
    heuristic_categories = (
        (("밥", "초밥", "치킨", "라면", "닭", "빵", "쿠키", "초콜릿", "커피", "맛집", "음식", "삼계탕", "보양식", "디저트"), "food_culinary"),
        ((
            "영화", "드라마", "예능", "웹툰", "애니", "극장", "방송",
            "ott", "시리즈", "블랙박스 리뷰", "트로트",
        ), "screen_content"),
        (("콘서트", "공연", "앨범", "노래", "뮤직", "아이돌", "생일"), "music_performance"),
        ((
            "아시안 게임", "아시안게임", "야구", "축구", "테니스", "농구", "선수", "야구 감독", "축구 감독",
            "농구 감독", "스포츠 감독", "타격왕",
            "프로골퍼", " fc",
        ), "sports_participation"),
        ((
            "게임", "패치", "롤 ", "오버워치", "스팀", "리그 오브 레전드",
            "mmorpg", "콘솔", "이스포츠", "e스포츠",
        ), "gaming_digital"),
        ((
            "패션", "한복", "유니폼", "가방", "신발", "화장품", "뷰티",
            "메이크업", "스킨케어", "향수", "네일", "헤어", "코스메틱",
        ), "fashion_collectible"),
        ((
            "여행", "호텔", "축제", "팝업", "전시", "박람회", "페스티벌",
            "도서전", "영화제", "행사", "엑스포", "컨벤션",
        ), "place_experience"),
        ((
            "뜨개질", "뜨개", "크로셰", "코바늘", "대바늘", "다꾸", "꾸미기",
            "홈카페", "캠핑", "피크닉", "취미", "공예", "핸드메이드",
        ), "lifestyle_behavior"),
        ((
            "러닝", "달리기", "요가", "필라테스", "명상", "헬스", "산책",
            "건강관리", "웰니스", "수면", "회복",
        ), "wellness_behavior"),
        ((
            "챌린지", "밈", "인증샷", "해시태그", "릴스", "숏폼", "바이럴",
        ), "participation_meme"),
        ((
            "주식", "증시", "코스피", "코스닥", "채권", "금리", "증권",
            "상장폐지", "가상자산", "나스닥", "다우 존스", "cpi", "국채",
        ), "investment_market"),
        (("스마트폰", "폴더블", "휴대폰", "신제품", "신모델"), "product_brand"),
        ((
            "로봇", "휴머노이드", "광 통신", "광통신", "인공지능", "원자로",
            "원전", "반도체", "데이터센터", "배터리", "자율주행",
        ), "technology_tool"),
        (("일식", "월식", "유성우", "별똥별", "천문 현상"), "public_observation_event"),
    )
    for markers, category in heuristic_categories:
        if any(marker in lowered for marker in markers):
            return category
    return "unclassified"


def _broad_category(category: str) -> str:
    """Map detailed internal labels to a compact frontend taxonomy."""
    mapping = {
        "food_culinary": "food",
        "seasonal_food_ritual": "food",
        "music_performance": "content",
        "screen_content": "content",
        "gaming_digital": "content",
        "sports_attendance": "sports",
        "sports_participation": "sports",
        "fashion_collectible": "lifestyle",
        "place_experience": "lifestyle",
        "lifestyle_behavior": "lifestyle",
        "wellness_behavior": "lifestyle",
        "participation_meme": "culture",
        "public_observation_event": "culture",
        "product_brand": "consumer",
        "technology_tool": "technology",
        "investment_market": "market",
        "policy_issue": "issue",
        "politics": "issue",
        "incident": "issue",
        "crime": "issue",
        "disaster": "issue",
        "weather_alert": "issue",
        "privacy_controversy": "issue",
    }
    return mapping.get(category, "other")


PUBLIC_BROAD_CATEGORY_LABELS = {
    "food": "음식·식품",
    "content": "음악·영상·게임 콘텐츠",
    "sports": "스포츠",
    "lifestyle": "패션·뷰티·여행·생활",
    "culture": "문화·밈·참여",
    "consumer": "제품·브랜드",
    "technology": "기술·도구",
    "market": "금융·시장",
}


def _category_label(broad_category: str) -> str:
    return PUBLIC_BROAD_CATEGORY_LABELS.get(
        broad_category,
        "이슈·검토" if broad_category == "issue" else "기타·검토",
    )


def _trend_definition(
    display_name: str,
    category_label: str,
    related_terms: list[str] | None = None,
    sources: list[str] | set[str] | tuple[str, ...] | None = None,
) -> str:
    category_meanings = {
        "음식·식품": "제품·메뉴·식문화에 대한 소비자 관심이 모이는 흐름",
        "음악·영상·게임 콘텐츠": "작품·공연·게임과 그 이용 경험에 관심이 모이는 흐름",
        "스포츠": "경기·대회·선수 또는 관람 활동에 관심이 모이는 흐름",
        "패션·뷰티·여행·생활": "장소·행사·스타일 또는 생활 경험에 관심이 모이는 흐름",
        "문화·밈·참여": "사람들이 관측·공유·참여하며 확산시키는 문화적 흐름",
        "제품·브랜드": "특정 제품이나 브랜드의 이용·구매 맥락에 관심이 모이는 흐름",
        "기술·도구": "기술·장비·인프라의 개발과 활용에 관심이 모이는 흐름",
        "금융·시장": "시장·자산·금융 서비스의 변화와 이용에 관심이 모이는 흐름",
    }
    meaning = category_meanings.get(
        category_label,
        "구체적인 대상과 그 이용 맥락에 관심이 모이는 흐름",
    )
    definition = f"'{display_name}' 키워드는 {meaning}입니다."
    display_key = normalize_event_key(display_name)
    contextual_terms = [
        term for term in dict.fromkeys(related_terms or [])
        if normalize_event_key(term) != display_key
    ][:2]
    if contextual_terms:
        definition += (
            f" 실측 데이터에서는 {', '.join(contextual_terms)} 같은 표현과 함께 나타났습니다."
        )
    observed_sources = {
        str(source).strip().casefold()
        for source in sources or []
        if str(source).strip().casefold() in {"x", "google_trends"}
    }
    if observed_sources == {"x", "google_trends"}:
        source_phrase = "X와 Google 대한민국 관측"
    elif observed_sources == {"google_trends"}:
        source_phrase = "Google Trending Now 대한민국 관측"
    elif observed_sources == {"x"}:
        source_phrase = "X 대한민국 실시간 트렌드 관측"
    else:
        source_phrase = "공개 원천 관측"
    definition += f" {source_phrase}에서 확인된 맥락입니다."
    return definition


_LIFECYCLE_PRESENTATION = {
    "insufficient_data": ("entry", 0, "진입", 12, "후보군에 진입했지만 비교 관측이 아직 부족합니다."),
    "new": ("detected", 1, "포착", 32, "새로운 관심 흐름으로 포착된 구간입니다."),
    "rising": ("spreading", 2, "확산", 62, "이전 관측 구간보다 관심이 커지는 흐름입니다."),
    "rebounding": ("spreading", 2, "확산", 68, "관심이 다시 높아지며 확산되는 흐름입니다."),
    "sustained": ("mainstream", 3, "대중화", 88, "반복 관측되며 대중 관심이 유지되는 구간입니다."),
    "cooling": ("mainstream", 3, "대중화", 92, "대중화 뒤 확산 속도가 완만해진 구간입니다."),
    "expired": ("mainstream", 3, "대중화", 100, "대중화 이력은 있으나 현재 관측은 종료된 상태입니다."),
}


def _attention_windows(item: dict) -> list[dict]:
    """Expose only the three periods used by the detail design.

    The source feeds provide ranks, not universal mention counts. The public
    metric is therefore named an attention-index change and never fabricated
    as an absolute mention volume.
    """

    changes = item.get("attention_change") or {}
    definitions = (
        ("1w", "1주", "1w"),
        ("1m", "1개월", "1m"),
        ("3m", "3개월", "3m"),
    )
    windows = []
    for key, label, change_key in definitions:
        value = dict(changes.get(change_key) or {})
        windows.append({
            "key": key,
            "label": label,
            "metric": "normalized_attention_index_change",
            "status": value.get("status", "unavailable"),
            "percent": value.get("percent"),
            "basis": value.get("basis", "previous_equal_period_score"),
            "is_absolute_mention_count": False,
        })
    return windows


def _frontend_story(item: dict) -> dict:
    """Build a source-faithful story payload for the supplied prototype UI.

    The UI needs more than an opaque score: it visualises a trigger, a small
    related-expression graph, a lifecycle stage, and source-by-source motion.
    This projection never creates a historical parent, a causal claim, or an
    invented percentage.  Each relation is explicitly labelled as observed
    co-occurrence or reviewed ontology context.
    """

    lifecycle = str(item.get("lifecycle") or "insufficient_data")
    stage_key, stage_index, phase_label, progress, phase_caption = _LIFECYCLE_PRESENTATION.get(
        lifecycle, _LIFECYCLE_PRESENTATION["insufficient_data"]
    )
    age_hours = max(0.0, float(item.get("age_hours") or 0.0))
    observed_day = max(1, int(age_hours // 24) + 1)
    context = item.get("context_research") or {}
    related = list(item.get("related_keywords") or item.get("keywords") or [])[:5]
    root_id = "trend:root"
    nodes = [{
        "id": root_id,
        "label": str(item.get("display_name") or item.get("event_key") or ""),
        "node_type": "observed_trend_expression",
        "source": "x_google_observation",
    }]
    edges = []
    for index, keyword in enumerate(related, 1):
        text = str(keyword.get("text") or "").strip()
        if not text:
            continue
        status = str(keyword.get("status") or "observed_related_query")
        observed = status in {"observed_ranked_term", "observed_related_query"}
        node_id = f"keyword:{index}"
        nodes.append({
            "id": node_id,
            "label": text,
            "node_type": "observed_related_expression" if observed else "reviewed_related_concept",
            "source": "x_google_observation" if observed else "reviewed_ontology",
        })
        evidence_urls = [
            str(url) for url in keyword.get("evidence_urls") or []
            if str(url).startswith(("http://", "https://"))
        ]
        edges.append({
            "from": root_id,
            "to": node_id,
            "relation_type": "source_related_query" if observed else "reviewed_related_concept",
            "relation_label": "동일 관측 맥락" if observed else "검수된 연관 맥락",
            "evidence_urls": list(dict.fromkeys(evidence_urls)),
            "causality": "not_inferred",
        })

    attention_change = (item.get("attention_change") or {}).get("1w") or {}
    if attention_change.get("status") == "measured" and attention_change.get("percent") is not None:
        percent = float(attention_change["percent"])
        lift = {
            "status": "measured",
            "metric": "previous_equal_period_score_change",
            "value": round(percent, 2),
            "unit": "percent",
            "label": f"1주 관심지수 {percent:+.1f}%",
        }
    elif item.get("momentum_delta") is not None:
        points = float(item.get("momentum_delta") or 0.0) * 100.0
        lift = {
            "status": "normalized_signal",
            "metric": "source_rank_velocity_index",
            "value": round(points, 2),
            "unit": "points",
            "label": f"관심 속도 지표 {points:+.1f}p",
        }
    else:
        lift = {
            "status": "unavailable",
            "metric": "source_rank_velocity_index",
            "value": None,
            "unit": "points",
            "label": "비교 관측 축적 중",
        }

    source_labels = {
        "x": "X",
        "google_trends": "Google Trends",
        "naver": "NAVER 검색·뉴스·블로그",
        "youtube": "YouTube KR 차트·검색",
    }
    latest_ranks = item.get("latest_source_ranks") or {}
    rank_changes = item.get("rank_change_by_source") or {}
    channels = []
    for source in ("x", "google_trends", "naver", "youtube"):
        if source not in latest_ranks and source != "naver":
            if source != "youtube":
                continue
        providers = ((item.get("verification_layer") or {}).get("providers") or {})
        if (
            source == "naver"
            and not providers.get(source)
        ):
            continue
        if (
            source == "youtube"
            and not providers.get(source)
            and not item.get("youtube_chart_signal")
        ):
            continue
        change = rank_changes.get(source)
        chart_signal = item.get("youtube_chart_signal") or {}
        source_rank = latest_ranks.get(source)
        if source == "youtube" and source_rank is None:
            source_rank = chart_signal.get("best_video_rank")
            change = chart_signal.get("rank_change")
        channels.append({
            "source": source,
            "label": source_labels[source],
            "latest_rank": source_rank,
            "rank_change": change,
            "movement_label": (
                f"직전 관측 대비 순위 {int(change):+d}" if change is not None else "직전 비교 자료 없음"
            ),
            "metric": "source_rank_change",
            "affects_canonical_observed_rank": source in {"x", "google_trends"},
            "affects_multisource_home_rank": bool(
                (item.get("home_platform_weights") or {}).get(source)
            ),
        })

    trigger_urls = [
        str(url) for url in context.get("evidence_urls") or []
        if str(url).startswith(("http://", "https://"))
    ]
    payload = {
        "schema_version": "trend-story-v1",
        "status": "ready" if context.get("status") == "ready" else "observed_context_only",
        "origin": {
            "observed_term": str(item.get("observed_representative_term") or ""),
            "first_observed_at": item.get("first_seen_at"),
            "trigger_title": str(context.get("trigger_title") or ""),
            "trigger_type": str(context.get("trigger_type") or ""),
            "why_now": str(context.get("why_now") or ""),
            "evidence_urls": list(dict.fromkeys(trigger_urls)),
            "assertion": "observed_trigger_or_context_not_causal_origin",
        },
        "relationship_graph": {
            "interpretation": "observed_context_graph_not_causal_lineage",
            "nodes": nodes,
            "edges": edges,
        },
        "diffusion": {
            "lifecycle": lifecycle,
            "trend_stage": {
                "key": stage_key,
                "label": phase_label,
                "index": stage_index,
            },
            "phase_label": phase_label,
            "stage_index": stage_index,
            "progress_percent": progress,
            "observed_day_label": f"관측 {observed_day}일차",
            "observed_hours": int((item.get("lifecycle_baseline") or {}).get("observed_hours") or 0),
            "caption": phase_caption,
            "attention_lift": lift,
            "attention_windows": _attention_windows(item),
            "channels": channels,
            "ranking_input_policy": HOME_SOURCE_POLICY_VERSION,
        },
    }
    return payload


def _attach_frontend_story(items: list[dict]) -> None:
    """Attach the non-scoring prototype projection after all metrics exist."""

    for item in items:
        story = _frontend_story(item)
        item["trend_story"] = story
        item["frontend_projection"] = {
            "trend_name": item.get("display_name"),
            "trend_category": item.get("category_label"),
            "trend_core": item.get("display_name"),
            "observed_day_label": story["diffusion"]["observed_day_label"],
            "phase_label": story["diffusion"]["phase_label"],
            "stage_index": story["diffusion"]["stage_index"],
            "progress_percent": story["diffusion"]["progress_percent"],
            "attention_lift": story["diffusion"]["attention_lift"],
            "attention_windows": story["diffusion"]["attention_windows"],
            "current_rank": item.get("home_rank") or item.get("observed_rank"),
            "caption": story["diffusion"]["caption"],
            "related_keyword_count": len(item.get("related_keywords") or []),
            "company_grouping": "company_role_category",
            "is_mock": False,
        }


def _home_context_gate(item: dict) -> tuple[bool, str]:
    """Apply a non-scoring evidence gate to the home representative subset.

    Every observed term remains in ``unified_ranking``.  The home subset is
    narrower: a term that still needs context must have at least one observable
    disambiguation signal (source-related expression, reviewed ontology path,
    matched verification provider, or linked news context).  This prevents a
    short homonym such as an unexplained name or noun from being presented as a
    resolved consumer trend merely because a category classifier chose a main
    lane.
    """

    context_status = str(item.get("context_status") or "")
    if item.get("lane") == "issue":
        return False, "not_main_lane"
    if item.get("lane") != "main" and context_status != "resolved_by_observed_context":
        return False, "not_main_lane"
    if item.get("category") in {"unclassified", "other"}:
        return False, "unclassified"
    if item.get("broad_category") not in PUBLIC_BROAD_CATEGORIES:
        return False, "unclassified"
    if context_status in {"unresolved", "ambiguous_person"}:
        return False, context_status
    if item.get("broad_category") == "market":
        labels = set((item.get("trend_fit") or {}).get("labels") or [])
        period_sources = set(item.get("period_sources") or [])
        has_market_context = bool(
            labels.intersection({"consumer_action", "productization", "cross_context"})
            or {"x", "google_trends"}.issubset(period_sources)
        )
        if not has_market_context:
            return False, "market_context_evidence_missing"
    context_research = item.get("context_research") or {}
    trigger_title = str(context_research.get("trigger_title") or "").strip()
    trigger_summary = str(context_research.get("why_now") or "").strip()
    trigger_urls = {
        str(value).strip()
        for value in context_research.get("evidence_urls") or []
        if str(value).strip().startswith(("http://", "https://"))
    }
    if not (
        context_research.get("status") == "ready"
        and trigger_title
        and trigger_summary
        and trigger_urls
    ):
        return False, "trigger_evidence_incomplete"
    if item.get("lane") != "main":
        return False, "not_main_lane"

    context_reason = "verified_trigger_event"
    if context_status == "needs_context":
        basis = str(item.get("category_basis") or "")
        labels = set((item.get("trend_fit") or {}).get("labels") or [])
        verification = item.get("verification_layer") or {}
        if basis == "raw_expression_general_rule" and labels:
            context_reason = "specific_observed_expression"
        elif basis == "observed_related_terms_general_rule" and labels:
            context_reason = "observed_related_expression"
        elif verification.get("status") == "observed" and verification.get("observed_platforms"):
            context_reason = "matched_verification_provider"
        elif (item.get("news_context") or {}).get("records"):
            context_reason = "linked_news_context"
        else:
            return False, "context_evidence_missing"

    return True, context_reason


def refresh_home_context_eligibility(intelligence: dict) -> dict:
    """Re-evaluate the non-scoring home context gate after provider research.

    The initial ranking is built before bounded provider requests finish.  A
    later verified article or video may resolve a concrete trigger, so this
    refresh is deliberately separate from ranking and category selection.
    """

    for item in intelligence.get("unified_ranking", []):
        allowed, reason = _home_context_gate(item)
        item["home_context_status"] = "resolved" if allowed else "review_required"
        item["home_context_reason"] = reason
        item["home_eligible"] = bool(allowed)
        if item.get("lane") == "main" and not allowed:
            item["selection_layer"] = "context_review_queue"
    return intelligence


def _series_rows(start: datetime, end: datetime, path: Path | None = None) -> list[sqlite3.Row]:
    with connect(path) as connection:
        return connection.execute(
            f"""SELECT observation.observed_at,observation.source,observation.topic,
                       observation.source_rank,observation.value,observation.provenance,
                       observation.source_payload_json,observation.related_terms_json
               FROM hourly_observations AS observation
               JOIN source_hour_quality AS quality
                 USING (observed_at, source, provenance)
               WHERE observation.observed_at BETWEEN ? AND ?
                 AND observation.provenance='observed'
                 AND {ELIGIBLE_COLLECTOR_SQL.replace('source', 'observation.source').replace('collector_version', 'observation.collector_version')}
                 AND quality.quality_status='eligible'
               ORDER BY observation.observed_at,observation.source,
                        observation.source_rank,observation.topic""",
            (floor_hour(start).isoformat(), floor_hour(end).isoformat()),
        ).fetchall()


def _representative_observed_term(
    observations: list[dict],
    *,
    current_at: str | None = None,
) -> tuple[str, dict]:
    """Choose a representative only from observed source expressions.

    Current source expressions take precedence for a current ranking. Within
    that set the deterministic order is repeated hours, number of sources,
    reciprocal-rank evidence, best rank, then normalized lexical order. This
    prevents an expired historical alias from replacing what users can see in
    the latest source page. No hand-written narrative or entity label can
    replace the source expression.
    """
    evidence: dict[str, dict] = {}
    for item in observations:
        raw = " ".join(str(item["topic"]).strip().split())
        bucket = evidence.setdefault(
            raw,
            {
                "hours": set(),
                "sources": set(),
                "current_sources": set(),
                "reciprocal_rank_support": 0.0,
                "best_rank": 10**9,
            },
        )
        bucket["hours"].add(item["observed_at"])
        bucket["sources"].add(item["source"])
        if current_at is not None and item["observed_at"] == current_at:
            bucket["current_sources"].add(item["source"])
        bucket["reciprocal_rank_support"] += 1.0 / (60.0 + item["source_rank"])
        bucket["best_rank"] = min(bucket["best_rank"], item["source_rank"])
    representative = min(
        evidence,
        key=lambda term: (
            -bool(evidence[term]["current_sources"]),
            -len(evidence[term]["hours"]),
            -len(evidence[term]["sources"]),
            -evidence[term]["reciprocal_rank_support"],
            evidence[term]["best_rank"],
            term.casefold(),
        ),
    )
    selected = evidence[representative]
    return representative, {
        "method": "current_observed_term_then_hours_sources_reciprocal_rank",
        "currently_observed": bool(selected["current_sources"]),
        "current_source_count": len(selected["current_sources"]),
        "observed_hours": len(selected["hours"]),
        "source_count": len(selected["sources"]),
        "reciprocal_rank_support": round(selected["reciprocal_rank_support"], 6),
        "best_source_rank": selected["best_rank"],
    }


def _related_term_evidence(observations: list[dict], representative: str) -> list[dict]:
    evidence: dict[str, dict] = {}
    for item in observations:
        raw_term = " ".join(str(item["topic"]).strip().split())
        if (
            raw_term
            and raw_term.casefold() != representative.casefold()
            and keyword_fits_public_label(raw_term)
        ):
            bucket = evidence.setdefault(raw_term, {"sources": set(), "hours": set(), "kind": "observed_ranked_term"})
            bucket["sources"].add(item["source"])
            bucket["hours"].add(item["observed_at"])
        try:
            related_terms = json.loads(item.get("related_terms_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            related_terms = []
        if not isinstance(related_terms, list):
            continue
        for related in related_terms:
            text = " ".join(str(related).strip().split())
            if (
                not text
                or text.casefold() == representative.casefold()
                or not keyword_fits_public_label(text)
            ):
                continue
            bucket = evidence.setdefault(text, {"sources": set(), "hours": set(), "kind": "observed_related_query"})
            bucket["sources"].add(item["source"])
            bucket["hours"].add(item["observed_at"])
    ordered = sorted(
        evidence.items(),
        key=lambda pair: (-len(pair[1]["hours"]), -len(pair[1]["sources"]), pair[0].casefold()),
    )

    def draft_role(text: str) -> str:
        compact = text.casefold().replace(" ", "")
        representative_key = representative.casefold().replace(" ", "")
        if representative_key and (
            compact in representative_key or representative_key in compact
        ):
            return "alias_or_variant"
        if any(marker in compact for marker in (
            "레시피", "만들기", "챌린지", "품절", "구매처", "오픈런",
            "맛집", "후기", "먹방", "예약", "관람", "방문", "콜라보",
        )):
            return "consumer_or_participation_signal"
        if any(marker in compact for marker in (
            "재료", "제품", "메뉴", "굿즈", "브랜드", "신곡", "시즌",
            "패치", "유니폼", "앨범", "출연진",
        )):
            return "component_or_product"
        return "review_required"

    return [
        {
            "text": text,
            "source": sorted(meta["sources"]),
            "observed_hours": len(meta["hours"]),
            "status": meta["kind"],
            "role": draft_role(text),
            "role_status": "deterministic_draft",
            "affects_score": False,
        }
        for text, meta in ordered[:5]
    ]


def _merge_reviewed_ontology_keywords(
    observed: list[dict],
    *,
    graph: OntologyGraph,
    representative: str,
    limit: int = 5,
) -> list[dict]:
    """Fill slots with reviewed aliases and non-alias related concepts."""

    selected = [
        item for item in observed
        if keyword_fits_public_label(item.get("text"))
    ][:limit]
    seen = {
        "".join(str(item.get("text") or "").casefold().split())
        for item in selected
    }
    seen.add("".join(representative.casefold().split()))
    reviewed_terms = graph.reviewed_aliases(representative)
    lookup = graph.lookup(representative)
    if lookup and lookup.get("match_type") != "exact_term" and lookup.get("evidence"):
        reviewed_terms = [
            {
                "label": lookup["target_node_label"],
                "evidence": lookup["evidence"],
            },
            *reviewed_terms,
        ]
    for alias in reviewed_terms:
        text = " ".join(str(alias.get("label") or "").strip().split())
        key = "".join(text.casefold().split())
        if not text or key in seen or not keyword_fits_public_label(text):
            continue
        evidence_urls = sorted({
            str(record.get("url") or "").strip()
            for record in alias.get("evidence", [])
            if str(record.get("url") or "").strip()
        })
        if not evidence_urls:
            continue
        seen.add(key)
        selected.append({
            "text": text,
            "source": ["reviewed_ontology"],
            "observed_hours": 0,
            "status": "approved_ontology_term",
            "role": "alias_or_variant",
            "role_status": "reviewed_evidence",
            "evidence_urls": evidence_urls,
            "affects_score": False,
        })
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for concept in graph.reviewed_related_terms(representative):
            text = " ".join(str(concept.get("label") or "").strip().split())
            key = "".join(text.casefold().split())
            if not text or key in seen or not keyword_fits_public_label(text):
                continue
            evidence_urls = sorted({
                str(record.get("url") or "").strip()
                for record in concept.get("evidence", [])
                if str(record.get("url") or "").strip()
            })
            if not evidence_urls:
                continue
            seen.add(key)
            selected.append({
                "text": text,
                "source": ["reviewed_ontology"],
                "observed_hours": 0,
                "status": "approved_ontology_related_term",
                "role": str(concept.get("relation_role") or "related_concept"),
                "role_status": "reviewed_evidence",
                "evidence_urls": evidence_urls,
                "affects_score": False,
            })
            if len(selected) >= limit:
                break
    return selected


def _hourly_and_daily_rankings(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    by_hour: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_hour[row["observed_at"]].append(row)
    hourly = []
    daily_events: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for stamp, hour_rows in sorted(by_hour.items()):
        available_sources = {row["source"] for row in hour_rows}
        denominator = max(len(available_sources) / 61.0, 1 / 61.0)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in hour_rows:
            grouped[canonical_topic(row["topic"])].append(row)
        ranked = []
        for event_key, event_rows in grouped.items():
            representative, representative_evidence = _representative_observed_term(
                event_rows,
                current_at=stamp,
            )
            best_by_source = {
                source: min((row for row in event_rows if row["source"] == source), key=lambda row: row["source_rank"])
                for source in {row["source"] for row in event_rows}
            }
            normalized_rrf = sum(1 / (60 + row["source_rank"]) for row in best_by_source.values()) / denominator
            ranked.append({
                "event_key": event_key,
                "representative_term": representative,
                "representative_evidence": representative_evidence,
                "raw_terms": sorted({row["topic"] for row in event_rows}),
                "normalized_rrf": round(normalized_rrf, 6),
                "source_ranks": {source: row["source_rank"] for source, row in sorted(best_by_source.items())},
            })
        ranked.sort(key=lambda item: (-item["normalized_rrf"], item["representative_term"].casefold()))
        for rank, item in enumerate(ranked, 1):
            item["rank"] = rank
            daily_events[((datetime.fromisoformat(stamp) + KST).date().isoformat(), item["event_key"])].append(item)
        hourly.append({"observed_at": stamp, "available_sources": sorted(available_sources), "ranking": ranked})

    daily = []
    for (kst_date, event_key), items in sorted(daily_events.items()):
        representative_counts = Counter(item["representative_term"] for item in items)
        representative = min(representative_counts, key=lambda term: (-representative_counts[term], term.casefold()))
        daily.append({
            "kst_date": kst_date,
            "event_key": event_key,
            "representative_term": representative,
            "hours_present": len(items),
            "best_rank": min(item["rank"] for item in items),
            "mean_rank": round(sum(item["rank"] for item in items) / len(items), 4),
            "source_count": len({source for item in items for source in item["source_ranks"]}),
        })
    daily.sort(key=lambda item: (item["kst_date"], item["best_rank"], item["representative_term"].casefold()))
    return hourly, daily


def _path_relation_tier(path_edges: list[dict]) -> str:
    """Classify business relevance without treating ``listed_as`` as proof."""

    business_edges = [
        edge for edge in path_edges if str(edge.get("relation_type")) != "listed_as"
    ]
    explicit_tiers = {
        str((edge.get("metadata") or {}).get("relation_tier") or "").strip()
        for edge in business_edges
    }
    explicit_tiers.discard("")
    # Ontology authors use the product-facing name ``industry_observation``;
    # the public contract historically calls the same tier ``adjacent``.
    # Normalize it here so an explicitly cautious industry observation can
    # never be promoted to the stronger value-chain tier by the fallback.
    if "industry_observation" in explicit_tiers:
        explicit_tiers.remove("industry_observation")
        explicit_tiers.add("adjacent")
    for tier in ("excluded", "adjacent", "value_chain", "core"):
        if tier in explicit_tiers:
            return tier

    relation_types = {
        str(edge.get("relation_type") or "").strip() for edge in business_edges
    }
    if relation_types & {
        "historical_business_link",
        "documented_business_relationship",
        "documented_product_market_participant",
        "denotes_listed_company",
    }:
        return "core"
    if relation_types & {"operates_in_industry", "industry_structure_supply"}:
        return "adjacent"
    if business_edges:
        return "value_chain"
    return "adjacent"


RELATION_TIER_PRESENTATION = {
    "core": {
        "strength": "direct",
        "company_role": "직접 기업",
        "label": "핵심 사업자",
        "horizon": "근거 확인 직접 관계",
        "exposure_status": "evidence_backed_direct_relevance",
        "display_type": "직접 관계",
    },
    "value_chain": {
        "strength": "indirect",
        "company_role": "플랫폼·채널",
        "label": "가치사슬 기업",
        "horizon": "근거 확인 가치사슬 관계",
        "exposure_status": "evidence_backed_value_chain_relevance",
        "display_type": "가치사슬",
    },
    "adjacent": {
        "strength": "sector_watch",
        "company_role": "인프라·서비스",
        "label": "산업 관찰기업",
        "horizon": "근거 확인 산업 관찰 관계",
        "exposure_status": "evidence_backed_industry_observation",
        "display_type": "산업 관찰",
    },
}

PUBLIC_RELATION_TIER = {
    "core": "direct",
    "value_chain": "value_chain",
    "adjacent": "industry_watch",
}


def _candidate_selection_priority(
    candidate: dict,
    representative: str,
) -> tuple[bool, int, int]:
    path = list(candidate.get("ontology_path") or [])
    return (
        str(candidate.get("matched_ontology_term") or "").casefold()
        == representative.casefold(),
        sum(step.get("review_status") == "approved" for step in path),
        -len(path),
    )


def _ontology_company_candidates(
    graph: OntologyGraph,
    *,
    representative: str,
    related_terms: list[dict],
    sources: set[str],
    as_of: str,
) -> tuple[list[dict], dict]:
    """Resolve observed terms through the reviewed graph without padding.

    A candidate is complete only when the checked-in ontology contains a
    forward, evidence-backed path all the way to a listed-stock node.  The
    historical seed is a relationship lookup, never a ranking input.
    """

    source_urls = {
        "x": "https://x.com/explore/tabs/trending",
        "google_trends": "https://trends.google.com/trending?geo=KR",
    }
    observed_urls = [source_urls[source] for source in sorted(sources) if source in source_urls]
    # Reviewed related concepts are presentation/enrichment evidence, not new
    # company-resolution roots.  Expanding companies from a second concept
    # (for example 나는 SOLO -> TVING -> every TVING partner) creates exactly
    # the kind of weak multi-hop association the product forbids.  Only source
    # observations and reviewed aliases may identify the same event root.
    company_seed_statuses = {
        "observed_ranked_term",
        "observed_related_query",
        "approved_ontology_term",
    }
    observed_terms = [
        {"text": representative, "status": "observed_representative"},
        *[
            {"text": item["text"], "status": item.get("status", "observed_related_query")}
            for item in related_terms
            if item.get("status", "observed_related_query") in company_seed_statuses
        ],
    ]
    unique_terms: list[dict] = []
    seen_terms: set[str] = set()
    for item in observed_terms:
        key = str(item["text"]).casefold()
        if key not in seen_terms:
            unique_terms.append(item)
            seen_terms.add(key)

    edge_by_id = {str(edge["id"]): edge for edge in graph.edges}
    by_stock: dict[str, dict] = {}
    term_diagnostics: list[dict] = []
    for observed in unique_terms:
        term = str(observed["text"])
        resolution = graph.resolve_term(
            term,
            min_companies=MINIMUM_PUBLISHED_COMPANIES,
            max_hops=7,
        )
        term_diagnostics.append(
            {
                "term": term,
                "observation_status": observed["status"],
                "ontology_status": resolution["status"],
                "ontology_company_count": resolution["company_count"],
                "lookup_match": resolution.get("match"),
            }
        )
        lookup_match = resolution.get("match")
        if lookup_match is None:
            continue
        start_node_id = str(lookup_match["target_node_id"])
        paths = graph.trace_paths(
            start_node_id,
            target_types=("stock",),
            max_hops=7,
            allowed_review_statuses=DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
        )
        for path in paths:
            nodes = [graph.node(node_id) for node_id in path.node_ids]
            # A reviewed path may pass through the observed company and then an
            # industry peer before reaching that peer's stock.  The company
            # represented by the terminal stock is therefore the last company
            # node on the path, not the first one.
            company_node = next(
                (node for node in reversed(nodes) if node["type"] == "company"),
                None,
            )
            stock_node = next((node for node in reversed(nodes) if node["type"] == "stock"), None)
            if not company_node or not stock_node:
                continue
            stock_code = str((stock_node.get("metadata") or {}).get("ticker") or "").strip()
            if not stock_code:
                continue

            ontology_path = [
                {
                    "from": representative,
                    "to": term,
                    "edge_type": (
                        "observed_term_exact_match"
                        if representative.casefold() == term.casefold()
                        else "observed_related_term"
                    ),
                    "evidence_urls": observed_urls,
                    "evidence_type": "source_page_observation",
                    "as_of": as_of,
                    "review_status": "observed",
                }
            ]
            evidence_records: list[dict] = []
            if lookup_match.get("match_type") != "exact_term":
                alias_records = list(lookup_match.get("evidence") or [])
                evidence_records.extend(alias_records)
                ontology_path.append(
                    {
                        "from": term,
                        "to": lookup_match["target_node_label"],
                        "edge_type": lookup_match["match_type"],
                        "evidence_urls": [record["url"] for record in alias_records],
                        "evidence_type": sorted(
                            {
                                str(record.get("evidence_type") or "documented_source")
                                for record in alias_records
                            }
                        ),
                        "as_of": next(
                            (
                                str(record.get("published_at"))
                                for record in alias_records
                                if record.get("published_at")
                            ),
                            as_of,
                        ),
                        "review_status": lookup_match["review_status"],
                    }
                )
            for edge_id in path.edge_ids:
                edge = edge_by_id[edge_id]
                records = [
                    graph.evidence_record(str(evidence_id))
                    for evidence_id in edge.get("evidence_ids", [])
                ]
                evidence_records.extend(records)
                ontology_path.append(
                    {
                        "from": graph.node(str(edge["from_node"]))["label"],
                        "to": graph.node(str(edge["to_node"]))["label"],
                        "edge_type": edge["relation_type"],
                        "evidence_urls": [record["url"] for record in records],
                        "evidence_type": sorted(
                            {str(record.get("evidence_type") or "documented_source") for record in records}
                        ),
                        "as_of": next(
                            (str(record.get("published_at")) for record in records if record.get("published_at")),
                            as_of,
                        ),
                        "review_status": edge["review_status"],
                    }
                )

            complete = bool(observed_urls) and all(
                edge["evidence_urls"]
                and edge["evidence_type"]
                and edge["as_of"]
                and edge["review_status"] in {
                    "observed", *DEFAULT_PUBLISHABLE_REVIEW_STATUSES,
                }
                for edge in ontology_path
            )
            path_edges = [edge_by_id[edge_id] for edge_id in path.edge_ids]
            business_edges = [
                edge for edge in path_edges if str(edge.get("relation_type")) != "listed_as"
            ]
            ontology_relation_tier = _path_relation_tier(path_edges)
            if ontology_relation_tier == "excluded":
                continue
            tier_presentation = RELATION_TIER_PRESENTATION[ontology_relation_tier]
            documented_role_category = next(
                (
                    str((edge.get("metadata") or {}).get("company_role_category") or "")
                    for edge in business_edges
                    if (edge.get("metadata") or {}).get("company_role_category")
                ),
                None,
            )
            first_evidence_url = next(
                (record["url"] for record in evidence_records if record.get("url")),
                None,
            )
            path_labels = [node["label"] for node in nodes]
            industry_labels = list(dict.fromkeys(
                node["label"] for node in nodes if node["type"] == "industry"
            ))
            evidence_sources = []
            seen_evidence_urls: set[str] = set()
            for record in evidence_records:
                url = str(record.get("url") or "").strip()
                if not url or url in seen_evidence_urls:
                    continue
                evidence_sources.append({
                    "url": url,
                    "title": record.get("title"),
                    "evidence_type": record.get("evidence_type"),
                    "published_at": record.get("published_at"),
                    "review_status": record.get("review_status"),
                })
                seen_evidence_urls.add(url)
            relation_reason = (
                f"관측어 '{term}'에서 {' → '.join(path_labels)}로 이어지는 "
                f"검수된 {len(path.edge_ids)}단계 온톨로지 경로"
            )
            company_summary = (
                f"{(stock_node.get('metadata') or {}).get('market') or '국내'} 상장기업, "
                f"종목코드 {stock_code}"
            )
            candidate = with_company_role({
                "company": company_node["label"],
                "stock_code": stock_code,
                "ticker": stock_code,
                "market": (stock_node.get("metadata") or {}).get("market"),
                "relation_type": (
                    str(business_edges[0]["relation_type"])
                    if business_edges
                    else "ontology_path"
                ),
                "strength": tier_presentation["strength"],
                "reason": relation_reason,
                "relationship_reason": relation_reason,
                "company_summary": company_summary,
                "company_description": company_summary,
                "business_features": industry_labels,
                "evidence_kind": "reviewed_ontology_path",
                "evidence_url": first_evidence_url,
                "evidence_sources": evidence_sources,
                "company_role": tier_presentation["company_role"],
                "company_role_category": documented_role_category,
                "relation_tier": PUBLIC_RELATION_TIER[ontology_relation_tier],
                "ontology_relation_tier": ontology_relation_tier,
                "relation_tier_label": tier_presentation["label"],
                # The source observation is current, but an ontology document may
                # be historical.  Do not turn evidence of a relationship into an
                # unsupported claim that the relationship is current or that the
                # stock has high exposure.
                "relation_horizon": tier_presentation["horizon"],
                "exposure_status": tier_presentation["exposure_status"],
                "verification_status": "ontology_evidence",
                "opportunity_status": "evidence_backed_candidate",
                "relation_display_type": tier_presentation["display_type"],
                "team_review_status": "ontology_reviewed",
                "team_review_label": "온톨로지 근거 검수됨",
                "investment_warning": "관계 분류는 주가 상승 예측이나 매수 추천이 아님",
                "matched_ontology_term": term,
                "matched_ontology_node": lookup_match["target_node_label"],
                "ontology_lookup_match_type": lookup_match["match_type"],
                "ontology_source": "reviewed_seed_plus_enrichment",
                "ontology_path": ontology_path,
                "ontology_complete": complete,
                "ontology_status": "complete" if complete else "incomplete",
            })
            previous = by_stock.get(stock_code)
            if complete and (
                previous is None
                or _candidate_selection_priority(candidate, representative)
                > _candidate_selection_priority(previous, representative)
            ):
                by_stock[stock_code] = candidate

    candidates = sorted(by_stock.values(), key=lambda item: (item["company"], item["stock_code"]))
    return candidates, {
        "seed_path": ONTOLOGY_SEED_PATH.name,
        "enrichment_paths": [path.name for path in ONTOLOGY_ENRICHMENT_PATHS],
        "minimum_gold_companies": MINIMUM_PUBLISHED_COMPANIES,
        "matched_terms": term_diagnostics,
        "padding_forbidden": True,
        "ranking_effect": "none",
    }


def _build_period_views(
    period_contract: dict,
    candidates: list[dict],
    *,
    full_detail_event_keys: set[str],
) -> tuple[list[dict], dict[str, dict]]:
    """Hydrate period scores with shared trend identity/classification only.

    Company, keyword, news and ontology payloads remain in the existing shared
    trend detail selected by ``detail_event_key``. Period views never rerun or
    duplicate company enrichment and company count cannot affect their rank.
    """

    base_by_key = {item["event_key"]: item for item in candidates}
    period_views: dict[str, dict] = {}
    periods = list(period_contract["periods"])
    for period in periods:
        key = period["key"]
        raw_view = period_contract["views"][key]
        ranking: list[dict] = []
        for raw_item in raw_view["unified_ranking"]:
            event_key = raw_item["event_key"]
            base = base_by_key.get(event_key)
            if base is None:
                raise ValueError(
                    f"period ranking event is absent from period identity set: {event_key}"
                )
            lifecycle = raw_item["lifecycle"]
            company_status = base.get("company_card_status")
            if not company_status:
                publish_status = (base.get("company_resolution") or {}).get(
                    "publish_status"
                )
                company_status = (
                    "ready"
                    if publish_status == "published"
                    else "enrichment_pending"
                    if base.get("company_eligible")
                    else "not_applicable"
                )
            ranking.append({
                "rank": raw_item["rank"],
                "observed_rank": raw_item["rank"],
                "main_rank": None,
                "home_rank": None,
                "publication_rank": None,
                "rising_rank": None,
                "event_key": event_key,
                "display_name": base["display_name"],
                "topic": base["topic"],
                "broad_category": base["broad_category"],
                "category": base["category"],
                "category_label": base["category_label"],
                "trend_definition": base["trend_definition"],
                "lane": base["lane"],
                "home_eligible": bool(base.get("home_eligible")),
                "score": raw_item["score"],
                "score_components": raw_item["score_components"],
                "candidate_status": raw_item["candidate_status"],
                "is_current": raw_item["is_current"],
                "period_sources": raw_item["period_sources"],
                "period_strength": raw_item["signals"]["period_strength"],
                # Kept as a migration alias; period_strength is the precise
                # name for this aggregate signal.
                "current_source_position": raw_item["signals"]["period_strength"],
                "momentum": raw_item["signals"]["momentum"],
                "momentum_delta": raw_item["signals"]["momentum_delta"],
                "persistence": raw_item["signals"]["persistence"],
                "freshness": raw_item["freshness"],
                "hours_since_last_seen": raw_item["hours_since_last_seen"],
                "previous_period_rank": raw_item["previous_period_rank"],
                "rank_change": raw_item["rank_change"],
                "rank_change_status": raw_item["rank_change_status"],
                "lifecycle": lifecycle["state"],
                "lifecycle_reason": lifecycle["reason_code"],
                "first_seen_at": raw_item["lifecycle_baseline"]["first_seen_at"],
                "last_seen_at": raw_item["last_seen_at"],
                "latest_source_ranks": base["latest_source_ranks"],
                "rank_change_by_source": base["rank_change_by_source"],
                "source_rank_change": base["rank_change_by_source"],
                "source_badge": base["source_badge"],
                "data_confidence": base["data_confidence"],
                "ranking_data_readiness": raw_item["data_readiness"],
                "company_card_status": company_status,
                "company_status": company_status,
                "keyword_status": base["keyword_status"],
                "frontend_readiness_status": base.get(
                    "frontend_readiness_status", "enrichment_pending"
                ),
                "frontend_readiness_missing": base.get(
                    "frontend_readiness_missing",
                    [
                        "related_keywords_exactly_five",
                        "evidence_backed_listed_companies_at_least_ten",
                    ],
                ),
                "frontend_keyword_count": int(base.get("frontend_keyword_count") or 0),
                "frontend_company_count": int(base.get("frontend_company_count") or 0),
                "detail_event_key": event_key,
                "detail_status": (
                    "shared_full_detail"
                    if event_key in full_detail_event_keys
                    else "period_summary_only"
                ),
                "shared_detail_fields": [
                    "keywords", "companies", "company_candidates",
                    "company_resolution", "verification_layer", "news_context",
                ],
            })
        ranking.sort(key=lambda item: item["rank"])
        main_ranking = [
            item for item in ranking
            if item["lane"] == "main" and item["home_eligible"]
        ]
        for main_rank, item in enumerate(main_ranking, 1):
            item["main_rank"] = main_rank
            item["home_rank"] = main_rank
        for publication_rank, item in enumerate(main_ranking, 1):
            item["publication_rank"] = publication_rank
        period_views[key] = {
            "key": key,
            "label": raw_view["label"],
            "default": raw_view["default"],
            "window": raw_view["window"],
            "formula_version": raw_view["formula_version"],
            "data_readiness": raw_view["data_readiness"],
            "company_detail_policy": "shared_by_detail_event_key",
            "company_count_affects_rank": False,
            "unified_ranking": ranking,
            "period_top10": select_balanced_home_top10(main_ranking),
        }
    return periods, period_views


def _resolved_home_selection_score(item: dict) -> tuple[float, dict[str, float]]:
    """Return the v4 selection score from the row's current public signals.

    Period views deliberately omit private top-level fields such as
    ``_home_selection_score``.  Recomputing from the synchronized signal fields
    keeps the hydrated daily view and the top-level compatibility alias on one
    deterministic selection contract instead of letting a missing/stale private
    cache change their order.
    """

    home_score = item.get("home_platform_score")
    if not isinstance(home_score, (int, float)):
        cached = item.get("_home_selection_score")
        if isinstance(cached, (int, float)):
            return float(cached), dict(item.get("_home_selection_components") or {})
        home_score = 0.0
    home_score = max(0.0, min(100.0, float(home_score)))
    momentum = max(0.0, min(1.0, float(item.get("momentum_delta") or 0.0)))
    latest_sources = {
        source
        for source, rank in (item.get("latest_source_ranks") or {}).items()
        if rank is not None
    }
    cross_spread = 1.0 if {"x", "google_trends"}.issubset(latest_sources) else 0.0
    persistence = max(0.0, min(1.0, float(item.get("persistence") or 0.0)))
    freshness_record = item.get("freshness")
    freshness_value = (
        freshness_record.get("signal")
        if isinstance(freshness_record, dict)
        else freshness_record
    )
    freshness = max(0.0, min(1.0, float(freshness_value or 0.0)))
    score = round(
        35.0 * momentum
        + 25.0 * cross_spread
        + 20.0 * (home_score / 100.0)
        + 10.0 * persistence
        + 10.0 * freshness,
        6,
    )
    return score, {
        "velocity": round(momentum * 100.0, 6),
        "cross_platform_spread": round(cross_spread * 100.0, 6),
        "current_attention": round(home_score, 6),
        "persistence": round(persistence * 100.0, 6),
        "recency": round(freshness * 100.0, 6),
    }


def select_balanced_home_top10(rows: list[dict], *, limit: int = 10) -> list[dict]:
    """Build the ranked compatibility Top10 without changing source rank.

    The new ``home_feed`` remains rank-free.  This helper exists for the
    current frontend contract: current evidence-complete events are preferred,
    a two-per-category soft cap improves early diversity, and any remaining
    slots are filled by score.  Recently observed resolved events may backfill
    only when the current pool has fewer than ``limit`` rows.
    """

    if limit <= 0:
        return []

    def order_key(item: dict) -> tuple:
        measured_rise = (
            (item.get("ranking_data_readiness") or {}).get("momentum_status") == "measured"
            and float(item.get("momentum_delta") or 0.0) > 0.0
        )
        return (
            -int(measured_rise),
            -_resolved_home_selection_score(item)[0],
            -float(item.get("score") or 0.0),
            int(item.get("observed_rank") or item.get("rank") or 10**9),
            str(item.get("event_key") or ""),
        )

    current = [
        item for item in rows
        if item.get("is_current") is True
    ]
    def has_observed_period_evidence(item: dict) -> bool:
        # Period summaries intentionally omit the heavy ``series`` payload.
        # ``period_observed`` plus an explicit X/Google ``period_sources`` list
        # is the compact, source-derived proof produced by Ranking V2; accepting
        # it keeps the daily hydrated alias equivalent without fabricating or
        # reusing an observation.
        period_sources = set(item.get("period_sources") or [])
        if (
            item.get("candidate_status") == "period_observed"
            and bool(period_sources & {"x", "google_trends"})
        ):
            return True
        return any(
            row.get("provenance") == "observed"
            and row.get("source") in {"x", "google_trends"}
            for row in item.get("series") or []
        )

    recent = [
        item for item in rows
        if item.get("is_current") is not True
        and has_observed_period_evidence(item)
        and float(item.get("hours_since_last_seen") or 10**9) <= 24.0
    ]

    selected: list[dict] = []
    selected_keys: set[str] = set()

    def extend(pool: list[dict], *, recent_context: bool = False) -> None:
        ordered = sorted(pool, key=order_key)
        category_counts: dict[str, int] = {}
        # A verified positive slope is the primary product signal.  It must
        # remain ahead of steady cards even when several rising events share
        # one category; diversity is a soft rule for the remaining slots.
        rising = [
            item for item in ordered
            if (item.get("ranking_data_readiness") or {}).get("momentum_status")
            == "measured"
            and float(item.get("momentum_delta") or 0.0) > 0.0
        ]
        for item in rising:
            if len(selected) >= limit:
                return
            key = str(item.get("event_key") or "")
            if not key or key in selected_keys:
                continue
            selected_item = dict(item)
            selected_item["home_mix_bucket"] = (
                "recent_context" if recent_context else "emerging"
            )
            selected_item["home_mix_policy"] = "multisource_velocity_mix_v4"
            selected.append(selected_item)
            selected_keys.add(key)
            category = str(item.get("broad_category") or "other")
            category_counts[category] = category_counts.get(category, 0) + 1
        for soft_cap in (2, None):
            for item in ordered:
                if len(selected) >= limit:
                    return
                key = str(item.get("event_key") or "")
                if not key or key in selected_keys:
                    continue
                category = str(item.get("broad_category") or "other")
                if soft_cap is not None and category_counts.get(category, 0) >= soft_cap:
                    continue
                selected_item = dict(item)
                measured_rise = (
                    (item.get("ranking_data_readiness") or {}).get("momentum_status")
                    == "measured"
                    and float(item.get("momentum_delta") or 0.0) > 0.0
                )
                selected_item["home_mix_bucket"] = (
                    "recent_context"
                    if recent_context
                    else "emerging"
                    if measured_rise
                    else "established"
                )
                selected_item["home_mix_policy"] = "multisource_velocity_mix_v4"
                selected.append(selected_item)
                selected_keys.add(key)
                category_counts[category] = category_counts.get(category, 0) + 1

    extend(current)
    if len(selected) < limit:
        extend(recent, recent_context=True)
    for publication_rank, item in enumerate(selected, 1):
        item["publication_rank"] = publication_rank
    return selected


def _flow_group(item: dict) -> str | None:
    """Map an evidence-complete 24-hour candidate to one honest flow state."""

    if not any(
        row.get("provenance") == "observed"
        and row.get("source") in {"x", "google_trends"}
        for row in item.get("series") or []
    ):
        return None
    sources = set((item.get("latest_source_ranks") or {}).keys())
    measured = (item.get("ranking_data_readiness") or {}).get("momentum_status") == "measured"
    positive = float(item.get("momentum_delta") or 0.0) > 0.0
    if item.get("is_current") is True and measured and positive and {"x", "google_trends"}.issubset(sources):
        return "spreading"
    if not measured or item.get("lifecycle") == "new":
        return "emerging"
    return "sustained"


def _home_card(item: dict, group: str) -> dict:
    """Return the public projection with ranking and scoring fields removed."""

    allowed = (
        "event_key", "display_name", "canonical_topic", "broad_category",
        "category", "category_label", "trend_definition", "lifecycle",
        "lifecycle_label", "source_badge", "sources", "period_sources", "context_research",
        "related_keywords", "keywords", "companies", "company_status",
        "company_card_status", "stock_impact_hypothesis", "data_confidence",
        "observed_at", "why_now", "verification_layer", "platform_observation_summary",
        "frontend_readiness_status", "company_card_reason", "disclaimer",
        "keyword_company_links",
    )
    card = {field: item[field] for field in allowed if field in item}
    card["flow_group"] = group
    return card


def _build_home_feed(rows: list[dict]) -> dict:
    """Create a rank-free user-facing feed; no quota, cap or padding applies."""

    labels = {
        "spreading": ("확산 중", "X·Google에서 함께 관측되고 실제 상승이 측정된 흐름"),
        "sustained": ("계속 화제", "현재 관측과 맥락은 유지되지만 급상승을 단정하지 않는 흐름"),
        "emerging": ("막 포착됨", "현재 맥락은 확인됐지만 비교 자료가 부족한 신규 흐름"),
    }
    buckets = {key: [] for key in labels}
    for item in rows:
        group = _flow_group(item)
        if group is not None:
            buckets[group].append(item)
    groups = []
    for key in ("spreading", "sustained", "emerging"):
        ordered = sorted(buckets[key], key=lambda item: (
            -float(item.get("_home_selection_score") or 0.0),
            -float(item.get("score") or 0.0),
            int(item.get("observed_rank") or 10**9),
            str(item.get("event_key") or ""),
        ))
        if ordered:
            label, definition = labels[key]
            groups.append({
                "key": key,
                "label": label,
                "definition": definition,
                "trends": [_home_card(item, key) for item in ordered],
            })
    return {
        "status": "ready" if groups else "empty",
        "groups": groups,
        "selection_policy": HOME_SOURCE_POLICY_VERSION,
        "legacy_alias_status": "deprecated_flattened_home_feed",
    }


def _naver_candidate_signal(item: dict) -> float | None:
    """Return a NAVER *news* signal without changing canonical rank.

    This is deliberately a bounded candidate-level context signal, not a
    NAVER keyword rank.  Only fresh news evidence and independent publishers
    are considered; blog, search-trend and video data cannot influence it.
    """

    providers = (item.get("verification_layer") or {}).get("providers") or {}
    record = providers.get("naver") or {}
    if record.get("matched") is not True or record.get("status") != "observed":
        return None
    metrics = record.get("metrics") or {}
    news_recent = min(10.0, float(metrics.get("news_recent_24h_sample_count") or 0.0)) * 10.0
    host_breadth = min(10.0, float(metrics.get("news_independent_host_count") or 0.0)) * 10.0
    return round(news_recent * 0.65 + host_breadth * 0.35, 6)


def _youtube_candidate_signal(item: dict) -> float | None:
    """Return a bounded candidate-level YouTube attention signal.

    ``mostPopular`` is a video chart, not a general Korean search-ranking
    feed.  The score therefore combines a fresh query match with the public
    statistics of its returned videos, then becomes comparable only through a
    percentile across the same candidate pool.  It never claims that views are
    search volume or that a video caused a trend.
    """

    providers = (item.get("verification_layer") or {}).get("providers") or {}
    record = providers.get("youtube") or {}
    query_signal: float | None = None
    if record.get("matched") is True and record.get("status") == "observed":
        metrics = record.get("metrics") or {}
        evidence = record.get("evidence") or []
        total = max(0.0, float(metrics.get("approximate_total_results") or 0.0))
        sample_count = max(0.0, float(metrics.get("stored_evidence_count") or 0.0))
        largest_view_count = max(
            [
                max(0.0, float((entry.get("metrics") or {}).get("viewCount") or 0.0))
                for entry in evidence
                if isinstance(entry, dict)
            ]
            or [0.0]
        )
        # Log scaling prevents a single celebrity MV from overwhelming every
        # other source.  It is a bounded discovery measure, not search volume.
        view_strength = min(100.0, math.log10(largest_view_count + 1.0) / 7.0 * 100.0)
        query_signal = (
            min(50.0, total) / 50.0 * 35.0
            + min(5.0, sample_count) / 5.0 * 20.0
            + view_strength * 0.45
        )

    chart = item.get("youtube_chart_signal") or {}
    chart_signal = None
    if chart.get("status") == "matched_exact_observed_expression":
        chart_signal = max(0.0, min(100.0, float(chart.get("youtube_score") or 0.0)))

    if query_signal is None and chart_signal is None:
        return None
    if query_signal is None:
        return round(chart_signal or 0.0, 6)
    if chart_signal is None:
        return round(query_signal, 6)
    # Search and official chart are independent content-discovery observations.
    # Keep the query slightly stronger because it is term-specific; both remain
    # subject to the equal-pool coverage gate before they affect home_rank.
    return round(query_signal * 0.60 + chart_signal * 0.40, 6)


def _percentiles(raw: dict[str, float | None]) -> dict[str, float]:
    ordered = sorted(
        ((key, float(value)) for key, value in raw.items() if value is not None),
        key=lambda pair: (-pair[1], pair[0]),
    )
    if not ordered:
        return {}
    return {
        key: round((len(ordered) - index) / len(ordered) * 100.0, 6)
        for index, (key, _) in enumerate(ordered)
    }


def apply_equal_platform_home_scores(rows: list[dict]) -> list[dict]:
    """Attach internal, deterministic selection signals for the home feed.

    The function name remains for one release of call-site compatibility.  It
    does *not* create a user-facing rank: canonical ``observed_rank`` remains
    the X/Google audit measure and the private selection score is used only to
    keep cards stable inside their flow group.
    """

    if not rows:
        return rows
    source_coverage = {
        "naver": {
            "active": False,
            "status": "context_only_not_comparable_rank_signal",
        }
    }

    source_max_rank: dict[str, int] = {}
    for source in ("x", "google_trends"):
        ranks = [
            int((item.get("latest_source_ranks") or {}).get(source))
            for item in rows
            if (item.get("latest_source_ranks") or {}).get(source) is not None
        ]
        source_max_rank[source] = max(ranks, default=1)

    def rank_strength(item: dict, source: str) -> float:
        value = (item.get("latest_source_ranks") or {}).get(source)
        if value is None:
            return 0.0
        rank = max(1, int(value))
        maximum = max(rank, source_max_rank[source])
        if maximum <= 1:
            return 100.0
        return max(0.0, min(100.0, (maximum - rank) / (maximum - 1) * 100.0))

    for item in rows:
        x_score = rank_strength(item, "x")
        google_score = rank_strength(item, "google_trends")
        weights = {"x": 0.5, "google_trends": 0.5}
        home_score = x_score * 0.5 + google_score * 0.5
        item["home_platform_score"] = round(home_score, 2)
        item["home_platform_components"] = {
            "x": round(x_score, 2),
            "google_trends": round(google_score, 2),
            "naver": None,
        }
        item["home_platform_weights"] = {source: round(weight, 6) for source, weight in weights.items()}
        item["naver_home_rank_status"] = source_coverage["naver"]["status"]
        item["youtube_home_rank_status"] = "disabled_by_home_feed_policy"
        item["naver_candidate_signal"] = _naver_candidate_signal(item)
        item["home_platform_coverage"] = {
            "candidate_pool_size": len(rows),
            "sources": source_coverage,
            "activation_threshold": None,
            "minimum_observed_candidates": None,
        }
        item["home_source_policy"] = HOME_SOURCE_POLICY_VERSION
        item["home_rank_input_sources"] = [
            source for source, weight in weights.items() if weight > 0.0
        ]
        naver_record = ((item.get("verification_layer") or {}).get("providers") or {}).get("naver") or {}
        naver_metrics = naver_record.get("metrics") or {}
        item["platform_observation_summary"] = {
            "x": {
                "observed": (item.get("latest_source_ranks") or {}).get("x") is not None,
                "latest_rank": (item.get("latest_source_ranks") or {}).get("x"),
                "ranking_input": True,
            },
            "google_trends": {
                "observed": (item.get("latest_source_ranks") or {}).get("google_trends") is not None,
                "latest_rank": (item.get("latest_source_ranks") or {}).get("google_trends"),
                "ranking_input": True,
            },
            "naver_news": {
                "observed": naver_record.get("status") == "observed" and naver_record.get("matched") is True,
                "recent_article_count": int(naver_metrics.get("news_recent_24h_sample_count") or 0),
                "independent_publisher_count": int(naver_metrics.get("news_independent_host_count") or 0),
                "selection_input": False,
            },
            "youtube": {"status": "disabled_by_home_feed_policy", "ranking_input": False},
            "instagram": {"status": "disabled_by_home_feed_policy", "ranking_input": False},
        }
        item["canonical_observed_rank_preserved"] = True

        (
            item["_home_selection_score"],
            item["_home_selection_components"],
        ) = _resolved_home_selection_score(item)
    return rows


def _period_change_metrics(period_views: dict[str, dict]) -> dict[str, dict]:
    """Return honest 1-week/1-month changes and an explicit 3-month gap."""

    output: dict[str, dict] = {}
    for key, label in (("weekly", "1w"), ("monthly", "1m")):
        for item in (period_views.get(key) or {}).get("unified_ranking") or []:
            previous = item.get("previous_period_score")
            current = item.get("score")
            if previous is None or current is None or float(previous) <= 0:
                metric = {
                    "status": "unavailable",
                    "percent": None,
                    "basis": "previous_equal_period_score",
                }
            else:
                metric = {
                    "status": "measured",
                    "percent": round(
                        (float(current) - float(previous)) / float(previous) * 100.0,
                        2,
                    ),
                    "basis": "previous_equal_period_score",
                }
            output.setdefault(str(item["event_key"]), {})[label] = metric
    for metrics in output.values():
        metrics["3m"] = {
            "status": "unavailable",
            "percent": None,
            "basis": "insufficient_90_day_observed_history",
        }
    return output


_KEYWORD_LINK_STOPWORDS = {
    "관련", "기업", "시장", "공식", "트렌드", "시간", "순위", "행사",
    "제품", "서비스", "대한민국", "한국",
}


def _attach_keyword_company_links(item: dict) -> None:
    """Explain keyword -> documented role -> listed-company connections."""

    keywords = list(item.get("related_keywords") or item.get("keywords") or [])
    companies = list(item.get("companies") or item.get("company_candidates") or [])
    keyword_by_key = {
        normalize_event_key(str(row.get("text") or "")): str(row.get("text") or "").strip()
        for row in keywords
        if isinstance(row, dict) and str(row.get("text") or "").strip()
    }
    links = []
    linked_keyword_keys: set[str] = set()
    for company in companies:
        company_name = str(company.get("company") or "").strip()
        if not company_name:
            continue
        explicit = {
            normalize_event_key(value)
            for value in company.get("matched_keywords") or []
            if str(value).strip()
        }
        haystack = " ".join(str(company.get(field) or "") for field in (
            "company_description", "company_summary", "relationship_reason",
            "reason", "company_role_label", "evidence_kind", "evidence_type",
        )).casefold()
        matched = []
        for normalized, text in keyword_by_key.items():
            if normalized in explicit:
                matched.append((text, "reviewed_keyword_company_bridge"))
                continue
            tokens = {
                token.casefold() for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text)
                if token.casefold() not in _KEYWORD_LINK_STOPWORDS
            }
            if tokens and any(token in haystack for token in tokens):
                matched.append((text, "document_text_overlap"))
        evidence_urls = [
            str(source.get("url") or "").strip()
            for source in company.get("evidence_sources") or []
            if isinstance(source, dict) and str(source.get("url") or "").startswith(("http://", "https://"))
        ]
        if not evidence_urls and str(company.get("evidence_url") or "").startswith(("http://", "https://")):
            evidence_urls = [str(company["evidence_url"])]
        company["matched_keywords"] = [text for text, _ in matched]
        reason = str(
            company.get("relationship_reason") or company.get("reason") or ""
        ).strip()
        role_label = str(company.get("company_role_label") or "역할 미확정")
        company["connection_explanation"] = (
            f"{', '.join(company['matched_keywords'])} 관련 맥락에서 {company_name}은(는) "
            f"'{role_label}' 역할로 연결됩니다. {reason}"
            if matched else
            f"{company_name}은(는) '{role_label}' 역할 후보입니다. {reason}"
        )
        for keyword, basis in matched:
            normalized = normalize_event_key(keyword)
            linked_keyword_keys.add(normalized)
            links.append({
                "keyword": keyword,
                "company": company_name,
                "stock_code": str(company.get("stock_code") or company.get("ticker") or ""),
                "company_role_category": company.get("company_role_category"),
                "company_role_label": company.get("company_role_label"),
                "relationship_reason": reason,
                "connection_explanation": company["connection_explanation"],
                "evidence_urls": list(dict.fromkeys(evidence_urls)),
                "match_basis": basis,
                "affects_rank": False,
            })
    # ``companies`` is the publishable subset and ``company_candidates`` is
    # the audit set. Keep common rows value-identical after adding the public
    # explanation fields so callers never see two contradictory versions of
    # the same ticker.
    enrichment_by_code = {
        str(company.get("stock_code") or company.get("ticker") or "").strip(): {
            "matched_keywords": list(company.get("matched_keywords") or []),
            "connection_explanation": str(
                company.get("connection_explanation") or ""
            ),
        }
        for company in companies
        if str(company.get("stock_code") or company.get("ticker") or "").strip()
    }
    for candidate in item.get("company_candidates") or []:
        code = str(
            candidate.get("stock_code") or candidate.get("ticker") or ""
        ).strip()
        if code in enrichment_by_code:
            candidate.update(enrichment_by_code[code])
    item["keyword_company_links"] = links
    item["linked_keyword_count"] = len(linked_keyword_keys)
    item["keyword_company_link_status"] = (
        "ready" if len(linked_keyword_keys) >= 2 else "enrichment_pending"
    )
    item["unlinked_related_keywords"] = [
        text for normalized, text in keyword_by_key.items()
        if normalized not in linked_keyword_keys
    ]


_PUBLIC_RELATION_TIER_LABELS = {
    "direct": "직접 관계",
    "value_chain": "가치사슬",
    "industry_watch": "산업 관찰",
}


def _normalize_final_company_record(company: dict) -> dict:
    """Fill public-contract labels from already reviewed company evidence."""

    normalized = dict(company)
    role = str(normalized.get("company_role_category") or "").strip()
    normalized["company_role_label"] = str(
        normalized.get("company_role_label")
        or COMPANY_ROLE_LABELS.get(role)
        or ""
    ).strip()
    relation_tier = str(
        normalized.get("relation_tier")
        or normalized.get("relationship_grade")
        or normalized.get("strength")
        or ""
    ).strip()
    normalized["relation_tier"] = relation_tier
    normalized["strength"] = relation_tier
    normalized.setdefault("ontology_relation_tier", relation_tier)
    relation_label = _PUBLIC_RELATION_TIER_LABELS.get(relation_tier, "")
    normalized["relation_tier_label"] = str(
        normalized.get("relation_tier_label") or relation_label
    ).strip()
    normalized["relation_display_type"] = str(
        normalized.get("relation_display_type") or relation_label
    ).strip()
    normalized["team_review_status"] = str(
        normalized.get("team_review_status") or "reviewed_enrichment_approved"
    ).strip()
    normalized["team_review_label"] = str(
        normalized.get("team_review_label") or "검수 완료"
    ).strip()
    normalized.setdefault("verification_status", "evidence_verified")
    normalized.setdefault("opportunity_status", "evidence_backed_candidate")

    evidence_sources = []
    evidence_urls = []
    for source in normalized.get("evidence_sources") or []:
        if not isinstance(source, dict):
            continue
        evidence = dict(source)
        url = str(evidence.get("url") or "").strip()
        if url:
            evidence_urls.append(url)
        evidence.setdefault("review_status", "approved")
        evidence.setdefault(
            "evidence_type", evidence.get("source_type") or "reviewed_public_source"
        )
        evidence_sources.append(evidence)
    normalized["evidence_sources"] = evidence_sources

    raw_path = list(normalized.get("ontology_path") or [])
    if raw_path and all(isinstance(node, str) for node in raw_path):
        normalized["ontology_path"] = [
            {
                "from": left,
                "to": right,
                "edge_type": "reviewed_relationship_path",
                "evidence_urls": list(dict.fromkeys(evidence_urls)),
                "review_status": "approved",
            }
            for left, right in zip(raw_path, raw_path[1:])
        ]
    return normalized


def _company_is_evidence_complete(company: dict) -> bool:
    evidence_urls = {
        str(source.get("url") or "").strip()
        for source in company.get("evidence_sources") or []
        if isinstance(source, dict) and str(source.get("url") or "").strip()
    }
    return bool(
        str(company.get("company") or "").strip()
        and str(company.get("stock_code") or "").strip()
        and str(company.get("market") or "").strip()
        and str(company.get("company_description") or "").strip()
        and str(company.get("relationship_reason") or "").strip()
        and evidence_urls
        and company.get("ontology_complete") is True
        and str(company.get("company_role_category") or "").strip()
        in PUBLIC_COMPANY_ROLE_CATEGORIES
        and str(company.get("company_role_label") or "").strip()
        and str(company.get("relation_tier") or "").strip()
        in _PUBLIC_RELATION_TIER_LABELS
        and str(company.get("relation_display_type") or "").strip()
        and str(company.get("team_review_status") or "").strip()
    )


def _synchronize_final_company_publication(item: dict) -> list[dict]:
    """Derive the Gold/public company state after every enrichment overlay.

    Reviewed caches may be attached after the deterministic candidate pass.
    They can complete presentation evidence, but never affect observed ranks.
    The final state is therefore derived solely from the final main/home gate
    and evidence-complete company records.  Anything else exposes no Gold rows.
    """

    source_rows = [
        _normalize_final_company_record(company)
        for company in [
            *(item.get("companies") or []),
            *(item.get("company_candidates") or []),
        ]
        if isinstance(company, dict)
    ]
    complete_by_stock: dict[str, dict] = {}
    for company in source_rows:
        if not _company_is_evidence_complete(company):
            continue
        stock_code = str(company.get("stock_code") or "").strip()
        complete_by_stock.setdefault(stock_code, company)
    complete_rows = list(complete_by_stock.values())
    projection = select_role_diverse_company_projection(
        complete_rows, limit=MINIMUM_FRONTEND_COMPANIES
    )
    role_categories = {
        str(company.get("company_role_category") or "").strip()
        for company in projection
    }
    linking_allowed = (
        item.get("lane") == "main"
        and item.get("home_eligible") is True
    )
    publishable = (
        linking_allowed
        and len(projection) == MINIMUM_FRONTEND_COMPANIES
        and public_company_role_count_is_valid(len(role_categories))
    )

    # Preserve every sourced record as internal research input, but expose the
    # exact public projection only after the full contract is satisfied.
    item["company_candidates"] = complete_rows
    item["companies"] = projection if publishable else []
    item["company_eligible"] = bool(linking_allowed)

    resolution = dict(item.get("company_resolution") or {})
    published_rows = item["companies"]
    tier_counts = {
        tier: sum(company.get("relation_tier") == tier for company in complete_rows)
        for tier in ("direct", "value_chain", "industry_watch")
    }
    candidate_roles = {
        str(company.get("company_role_category") or "").strip()
        for company in complete_rows
        if str(company.get("company_role_category") or "").strip()
        in PUBLIC_COMPANY_ROLE_CATEGORIES
    }
    resolution.update({
        "status": "published" if publishable else (
            "enrichment_pending" if linking_allowed else "excluded_by_context"
        ),
        "publish_status": "published" if publishable else "not_published",
        "candidate_count": len(complete_rows),
        "ontology_complete_count": len(complete_rows),
        "published_count": len(published_rows),
        "minimum_gold_companies": MINIMUM_FRONTEND_COMPANIES,
        "score_independent_of_company_count": True,
        "direct_count": sum(
            company.get("relation_tier") == "direct" for company in complete_rows
        ),
        "role_coverage": sorted(candidate_roles),
        "tier_counts": tier_counts,
        "category_count": len(role_categories) if publishable else 0,
        "candidate_category_count": len(candidate_roles),
        "role_category_counts": {
            role: sum(
                company.get("company_role_category") == role
                for company in (published_rows if publishable else complete_rows)
            )
            for role in sorted(role_categories if publishable else candidate_roles)
        },
        "reason": (
            "evidence_backed_ten_companies_across_three_to_four_roles"
            if publishable
            else "fewer_than_ten_evidence_backed_companies"
            if len(complete_rows) < MINIMUM_FRONTEND_COMPANIES
            else "company_linking_not_allowed_for_lane_or_context"
            if not linking_allowed
            else "company_publication_contract_incomplete"
        ),
    })
    resolution.setdefault("ontology_diagnostics", {
        "padding_forbidden": True,
        "ranking_effect": "none",
    })
    item["company_resolution"] = resolution
    item["company_card_status"] = (
        "ready" if publishable else
        "enrichment_pending" if linking_allowed else
        "not_applicable"
    )
    item["company_status"] = item["company_card_status"]
    item["company_card_reason"] = (
        "evidence_backed_ten_or_more" if publishable else
        "company_publication_contract_incomplete" if linking_allowed else
        "company_linking_not_allowed_for_lane_or_context"
    )
    return published_rows


def refresh_frontend_readiness(intelligence: dict) -> dict:
    """Rebuild frontend arrays after score-independent enrichment is attached."""

    refresh_home_context_eligibility(intelligence)
    candidates = intelligence.get("unified_ranking", [])
    for item in candidates:
        _synchronize_final_company_publication(item)
        _attach_keyword_company_links(item)
        keyword_rows = list(item.get("related_keywords") or item.get("keywords") or [])
        keyword_count = len(keyword_rows)
        keyword_lengths_valid = all(
            keyword_fits_public_label(row.get("text") if isinstance(row, dict) else row)
            for row in keyword_rows
        )
        readiness_company_rows = (
            item.get("companies") or item.get("company_candidates") or []
            if item.get("company_eligible")
            else item.get("companies") or []
        )
        complete_companies = [
            company for company in readiness_company_rows
            if _company_is_evidence_complete(company)
        ]
        complete_company_count = len({
            str(company["stock_code"]).strip() for company in complete_companies
        })
        role_category_count = len({
            str(company.get("company_role_category") or "").strip()
            for company in complete_companies
            if str(company.get("company_role_category") or "").strip()
        })
        missing = []
        if item.get("keyword_status") != "ready" or keyword_count != 5:
            missing.append("related_keywords_exactly_five")
        if not keyword_lengths_valid:
            missing.append("related_keywords_max_six_characters")
        if int(item.get("linked_keyword_count") or 0) < 2:
            missing.append("related_keywords_linked_to_companies_at_least_two")
        if complete_company_count < MINIMUM_FRONTEND_COMPANIES:
            missing.append("evidence_backed_listed_companies_at_least_ten")
        elif not public_company_role_count_is_valid(role_category_count):
            missing.append("company_role_categories_between_three_and_four")
        item["frontend_readiness_status"] = "ready" if not missing else "enrichment_pending"
        item["frontend_readiness_missing"] = missing
        item["frontend_keyword_count"] = keyword_count
        item["frontend_company_count"] = complete_company_count
        item["frontend_company_role_category_count"] = role_category_count
        item["publication_rank"] = None

    home = [
        item for item in candidates
        if item.get("lane") == "main" and item.get("home_eligible") is True
    ]
    apply_equal_platform_home_scores(home)
    for item in candidates:
        item["home_rank"] = None
    for home_rank, item in enumerate(home, 1):
        item["home_rank"] = home_rank

    # Period views are created before provider/context enrichment finishes.
    # Reconcile their non-scoring eligibility/readiness fields here so an
    # article that resolves context cannot leave stale ranks or Top10 aliases.
    final_state = {
        str(item.get("event_key") or ""): {
            "home_eligible": item.get("home_eligible") is True,
            "frontend_readiness_status": item.get("frontend_readiness_status"),
        }
        for item in candidates
        if str(item.get("event_key") or "")
    }
    for view in (intelligence.get("ranking_views") or {}).values():
        period_rows = view.get("unified_ranking") or []
        for row in period_rows:
            state = final_state.get(str(row.get("event_key") or ""))
            if state:
                row.update(state)
            row["main_rank"] = None
            row["home_rank"] = None
            row["publication_rank"] = None
        period_main = [
            row for row in period_rows
            if row.get("lane") == "main" and row.get("home_eligible") is True
        ]
        for main_rank, row in enumerate(period_main, 1):
            row["main_rank"] = main_rank
            row["home_rank"] = main_rank
        ready_period_main = [
            row for row in period_main
            if row.get("frontend_readiness_status") == "ready"
        ]
        view["period_top10"] = select_balanced_home_top10(ready_period_main)

    complete = [item for item in home if item.get("frontend_readiness_status") == "ready"]
    # ``home_feed`` is the only new public home surface.  It contains neither
    # cardinal ranks nor internal selection scores; incomplete observed rows
    # remain available only through the audit/detail arrays.
    feed = _build_home_feed(complete)
    flattened = [item for group in feed["groups"] for item in group["trends"]]
    compatibility_top10 = select_balanced_home_top10(complete)
    intelligence["home_feed"] = feed
    # One-release compatibility aliases.  They intentionally flatten the
    # exact same cards and are documented as deprecated.
    intelligence["home_top10"] = list(compatibility_top10)
    intelligence["trend_top10"] = list(compatibility_top10)
    intelligence["public_top10"] = list(compatibility_top10)
    intelligence["rising_top10"] = select_balanced_home_top10([
        item for item in complete if _flow_group(item) == "spreading"
    ])
    intelligence["company_ready_trends"] = [
        item for item in home
        if int(item.get("frontend_company_count") or 0) >= MINIMUM_FRONTEND_COMPANIES
    ]
    readiness = intelligence.setdefault("publication_readiness", {})
    home_status = feed["status"]
    readiness.update({
        "policy_version": "home-feed-contract-v1",
        "ready_count": len(complete),
        "published_count": len(compatibility_top10),
        "pending_count": len(home) - len(complete),
        "publication_ready": bool(flattened),
        "home_status": home_status,
    })
    readiness.pop("target_count", None)
    intelligence["home_status"] = home_status
    for summary in intelligence.get("category_summary", []):
        category = summary.get("category")
        summary["home_feed_count"] = sum(
            item.get("broad_category") == category for item in flattened
        )
        summary["spreading_count"] = sum(
            item.get("broad_category") == category
            for group in feed["groups"] if group["key"] == "spreading"
            for item in group["trends"]
        )
    by_key = {item["event_key"]: item for item in candidates}
    for view in (intelligence.get("ranking_views") or {}).values():
        for summary in view.get("unified_ranking", []):
            source = by_key.get(summary.get("event_key"))
            if source is None:
                continue
            for field in (
                "home_eligible",
                "home_platform_score", "home_platform_components",
                "home_platform_weights", "home_platform_coverage",
                "home_source_policy", "home_rank_input_sources",
                "canonical_observed_rank_preserved", "naver_home_rank_status",
                "naver_candidate_signal",
                "keyword_status", "company_card_status", "company_status",
                "frontend_readiness_status", "frontend_readiness_missing",
                "frontend_keyword_count", "frontend_company_count",
                "verification_layer",
            ):
                value = source.get(field)
                if value is None:
                    summary.pop(field, None)
                else:
                    summary[field] = value
        period_home = [
            item for item in view.get("unified_ranking", [])
            if item.get("lane") == "main"
            and item.get("home_eligible") is True
            and item.get("frontend_readiness_status") == "ready"
        ]
        view["period_home_feed"] = _build_home_feed(period_home)
        view["period_top10"] = select_balanced_home_top10(period_home)
    _attach_frontend_story(candidates)
    return intelligence


def build_intelligence(
    at: datetime,
    *,
    hours: int = 24,
    path: Path | None = None,
    news_context_by_term: dict[str, dict] | None = None,
) -> dict:
    end = floor_hour(at)
    start = end - timedelta(hours=max(1, hours) - 1)
    requested_rows = [dict(row) for row in _series_rows(start, end, path)]
    # Period views are true aggregates.  Hydration therefore needs every
    # event that can appear in the longest public view (30 days), while the
    # 60-day ledger remains lifecycle-only and never contributes score.
    period_start = end - timedelta(hours=720 - 1)
    rows = [dict(row) for row in _series_rows(period_start, end, path)]
    lifecycle_start = end - timedelta(days=60)
    ranking_rows = _assign_canonical_topics(
        [dict(row) for row in _series_rows(lifecycle_start, end, path)]
    )
    period_ranking_contract = build_period_rankings_v2(
        ranking_rows,
        at=end,
    )
    default_period = period_ranking_contract["default_period"]
    default_ranking_contract = period_ranking_contract["views"][default_period]
    ranking_v2 = {
        "formula_version": default_ranking_contract["formula_version"],
        "data_readiness": default_ranking_contract["data_readiness"],
        "parameters": default_ranking_contract["parameters"],
        "ranking": default_ranking_contract["unified_ranking"],
    }
    ranking_v2_by_key = {
        item["event_key"]: item for item in ranking_v2["ranking"]
    }
    monthly_ranking_by_key = {
        item["event_key"]: item
        for item in period_ranking_contract["views"]["monthly"]["unified_ranking"]
    }
    hourly_ranking, daily_aggregates = _hourly_and_daily_rankings(requested_rows)
    weekly_start = end - timedelta(hours=168 - 1)
    eligible_hours = sorted({
        row["observed_at"]
        for row in rows
        if row["observed_at"] >= weekly_start.isoformat()
    })
    eligible_hour_count = len(eligible_hours)
    snapshot_sizes = Counter((row["observed_at"], row["source"]) for row in rows)
    source_times: dict[str, list[str]] = defaultdict(list)
    for stamp, source in sorted(snapshot_sizes):
        source_times[source].append(stamp)
    current_available_sources = {
        source for source, stamps in source_times.items() if stamps and stamps[-1] == end.isoformat()
    }
    quality_rows = source_hour_quality(
        start,
        end,
        path,
    )
    quarantined_source_hours = [
        row for row in quality_rows if row["quality_status"] != "eligible"
    ]
    verification_by_trend = latest_verification_by_trend(path or default_db_path())
    ontology_graph = OntologyGraph.load_merged(
        ONTOLOGY_SEED_PATH,
        *ONTOLOGY_ENRICHMENT_PATHS,
    )
    news_context_by_term = news_context_by_term or {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _assign_canonical_topics(rows):
        grouped[item["canonical_topic"]].append(item)

    candidates = []
    for event_key, observations in grouped.items():
        observations.sort(key=lambda item: (item["observed_at"], item["source"], item["source_rank"]))
        sources = {item["source"] for item in observations}
        representative_term, representative_evidence = _representative_observed_term(
            observations,
            current_at=end.isoformat(),
        )
        event_resolution = resolve_event(event_key, sources)
        observed_hours = len({item["observed_at"] for item in observations})
        history_by_source: dict[str, list[dict]] = defaultdict(list)
        for item in observations:
            history_by_source[item["source"]].append(item)
        current_by_source = {}
        for source in current_available_sources:
            current_rows = [
                item for item in history_by_source.get(source, [])
                if item["observed_at"] == end.isoformat()
            ]
            if current_rows:
                current_by_source[source] = min(current_rows, key=lambda item: item["source_rank"])

        latest_by_source = {
            source: max(source_rows, key=lambda item: item["observed_at"])
            for source, source_rows in history_by_source.items()
            if source_rows
        }

        # The default/top-level contract is the true 24-hour aggregate.  A
        # longer-period-only event is hydrated for its period view but is not
        # resurrected into the daily alias.
        ranking_contract = (
            ranking_v2_by_key.get(event_key)
            or monthly_ranking_by_key[event_key]
        )
        score = ranking_contract["score"]
        score_components = ranking_contract["score_components"]
        current_signal = ranking_contract["signals"]["period_strength"]
        momentum = ranking_contract["signals"]["momentum"]
        persistence = ranking_contract["signals"]["persistence"]
        lifecycle_contract = ranking_contract["lifecycle"]
        lifecycle = lifecycle_contract["state"]
        lifecycle_reason = lifecycle_contract["reason_code"]
        lifecycle_baseline = ranking_contract["lifecycle_baseline"]
        maturity_values = list(
            ranking_contract["data_readiness"].get("coverage_by_source", {}).values()
        )
        history_maturity = (
            sum(maturity_values) / len(maturity_values) if maturity_values else 0.0
        )
        first_seen = lifecycle_baseline["first_seen_at"]
        last_seen = lifecycle_baseline["last_seen_at"]
        first_seen_dt = datetime.fromisoformat(first_seen)
        age_hours = max(0, int((end - first_seen_dt).total_seconds() // 3600))
        rank_changes = {}
        for source, latest_item in latest_by_source.items():
            previous_items = sorted(
                (
                    item for item in history_by_source.get(source, [])
                    if item["observed_at"] < latest_item["observed_at"]
                ),
                key=lambda item: item["observed_at"],
            )
            rank_changes[source] = (
                previous_items[-1]["source_rank"] - latest_item["source_rank"]
                if previous_items
                else None
            )
        phenomenon_summary = observation_summary(representative_term, sources)
        observed_keyword_items = _related_term_evidence(
            observations,
            representative_term,
        )
        keyword_items = _merge_reviewed_ontology_keywords(
            observed_keyword_items,
            graph=ontology_graph,
            representative=representative_term,
        )
        # Manual reference/alias data may help a reviewer understand a term,
        # but it must not promote the term into the product-fit lane. Category
        # selection starts from general lexical rules and observed related
        # terms only.
        detected_category = _category(event_key)
        category_basis = (
            "raw_expression_general_rule"
            if detected_category != "unclassified"
            else "unclassified"
        )
        if detected_category == "unclassified" and observed_keyword_items:
            # Google related queries are observed source evidence, not an LLM
            # guess. Reviewed ontology/cache keywords are intentionally not
            # consulted here because they must not affect product fit.
            detected_category = _category(" ".join(
                [event_key, *(item["text"] for item in observed_keyword_items)]
            ))
            if detected_category != "unclassified":
                category_basis = "observed_related_terms_general_rule"
        context_keys = {
            "".join(str(value).casefold().split())
            for value in [representative_term, event_key, *{item["topic"] for item in observations}]
        }
        news_context_records = [
            record for key, record in news_context_by_term.items()
            if "".join(str(key).casefold().split()) in context_keys
            and record.get("core_source_gate") == "satisfied_by_x_or_google"
        ]
        news_claim_types = sorted({
            str(claim_type)
            for record in news_context_records
            for claim_type in record.get("claim_types", [])
            if claim_type
        })
        approved_context_records = [
            evidence
            for record in news_context_records
            for evidence in record.get("evidence") or []
            if isinstance(evidence, dict)
            and str(evidence.get("review_status") or "") == "approved"
            and str(evidence.get("url") or "").startswith(("http://", "https://"))
            and str(evidence.get("title") or "").strip()
            and any(
                str(claim.get("text") or "").strip()
                for claim in evidence.get("claims") or []
                if isinstance(claim, dict)
            )
        ]
        trigger_record = approved_context_records[0] if approved_context_records else None
        trigger_claims = (
            [
                str(claim.get("text") or "").strip()
                for claim in trigger_record.get("claims") or []
                if isinstance(claim, dict) and str(claim.get("text") or "").strip()
            ]
            if trigger_record else []
        )
        context_research = {
            "status": "ready" if trigger_record and trigger_claims else "incomplete",
            "trigger_title": str((trigger_record or {}).get("title") or ""),
            "why_now": " ".join(trigger_claims),
            "trigger_type": (
                str((trigger_record.get("claims") or [{}])[0].get("type") or "")
                if trigger_record else ""
            ),
            "published_at": (trigger_record or {}).get("published_at"),
            "evidence_urls": [str(trigger_record["url"])] if trigger_record else [],
            "evidence_records": approved_context_records,
            "affects_score": False,
            "ranking_source": False,
        }
        verification_record = verification_by_trend.get(event_key, {})
        providers = verification_record.get("providers", {})
        provider_issue_context = _provider_issue_context_titles(
            providers,
            representative_term,
        )
        observed_context_terms = [item["text"] for item in observed_keyword_items]
        provider_context_terms = list(provider_issue_context)
        if detected_category == "unclassified" and provider_context_terms:
            provider_category = _category(" ".join(
                [event_key, *provider_context_terms]
            ))
            if provider_category != "unclassified":
                detected_category = provider_category
                category_basis = "verification_context_general_rule"
        fit_assessment = assess_trend_fit(
            representative_term,
            category=detected_category,
            context_terms=[*observed_context_terms, *provider_context_terms],
            issue_context_terms=provider_issue_context,
            news_claim_types=news_claim_types,
        )
        lane = fit_assessment["selection"]
        reason = fit_assessment["reason"]
        context_status = event_resolution["context_status"]
        if (
            context_status == "ambiguous_person"
            and detected_category != "unclassified"
            and (observed_keyword_items or provider_context_terms)
        ):
            # A person's raw name remains unchanged, but observed Google/X
            # context such as "축구 선수" can resolve the homonym for this
            # snapshot. No generated biography or guessed identity is used.
            context_status = "resolved_by_observed_context"
        # The home contract is the first ten rows of the main lane, so an
        # unresolved homonym must not be put in that lane and then removed by
        # a second hidden filter. Context evidence resolves the term before
        # this decision; otherwise the observed item remains in the review
        # lane with its global score and rank unchanged.
        # Category output and reviewed enrichment are not context evidence for
        # selection. Only source-observed related expressions, explicit
        # provider/news context, or a concrete lexical signal may resolve it.
        generic_context_word = representative_term.casefold() in {
            "음식", "제품", "브랜드", "콘텐츠", "생활", "문화", "기술", "애니"
        }
        context_evidence_present = bool(
            fit_assessment["labels"]
            and not generic_context_word
            and (
                category_basis == "raw_expression_general_rule"
                or observed_keyword_items
                or provider_context_terms
                or news_context_records
            )
        )
        if lane != "issue" and (
            (context_status in {"unresolved", "ambiguous_person"} and not context_evidence_present)
            or (context_status == "needs_context" and not context_evidence_present)
        ):
            lane = "review"
            reason = "원문은 보존하되 대표 사건·현상의 문맥을 아직 확인하지 못함"
        trend_fit = {
            **fit_assessment,
            "selection": lane,
            "main_eligible": lane == "main",
            "lane": lane,
            "label": {
                "main": "메인 트렌드 적합",
                "issue": "이슈·주의",
                "review": "맥락 검토",
            }[lane],
            "affects_score": False,
        }
        selection_layer = {
            "main": "main_subset",
            "issue": "issue_context",
            "review": "review_queue",
        }[lane]
        if (
            eligible_hour_count >= OPERATIONAL_HISTORY_TARGET_HOURS
            and len(sources) >= 2
            and observed_hours >= 6
        ):
            data_confidence = {"level": "high", "label": "높음",
                               "reason": "48시간 이상 원장과 양 플랫폼 반복 관측",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "mature"}
        elif eligible_hour_count >= MVP_HISTORY_HOURS and observed_hours >= 2:
            data_confidence = {"level": "medium", "label": "보통",
                               "reason": "24시간 MVP 원장과 반복 관측을 충족한 운영 초기 결과",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "mature"}
        elif eligible_hour_count >= 6:
            data_confidence = {"level": "low", "label": "낮음",
                               "reason": "원장 축적이 24시간 미만인 잠정 순위",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "provisional"}
        else:
            data_confidence = {"level": "very_low", "label": "초기 표본",
                               "reason": "원장 축적이 6시간 미만이라 현재 순위만 확인 가능",
                               "window_observed_hours": eligible_hour_count,
                               "history_maturity": round(history_maturity, 4),
                               "ranking_status": "provisional"}
        verification_layer = {
            **verification_record,
            "status": (
                "observed"
                if any(record.get("matched") for record in providers.values())
                else "unavailable"
                if providers
                else "not_run"
            ),
            "observed_platforms": sorted(
                provider for provider, record in providers.items() if record.get("matched")
            ),
            "affects_score": False,
        }
        sensitive_context = any(is_sensitive_context(item["topic"]) for item in observations)
        compact_event_key = "".join(event_key.split())
        company_eligible = (
            lane != "issue"
            and not sensitive_context
            and not (len(compact_event_key) == 6 and compact_event_key.isdigit())
        )
        # Monthly-only rows are intentionally period summaries.  Do not run
        # expensive company enrichment for an event that has no shared weekly
        # detail card; its summary truthfully remains enrichment_pending.
        should_enrich_company = company_eligible and event_key in ranking_v2_by_key
        if should_enrich_company:
            company_candidates, ontology_diagnostics = _ontology_company_candidates(
                ontology_graph,
                representative=representative_term,
                related_terms=keyword_items,
                sources=sources,
                as_of=last_seen,
            )
            candidate_company_categories, company_candidates = expand_value_chain(
                event_key,
                detected_category,
                company_candidates,
            )
        else:
            company_candidates = []
            candidate_company_categories = []
            ontology_diagnostics = {
                "seed_path": ONTOLOGY_SEED_PATH.name,
                "enrichment_paths": [path.name for path in ONTOLOGY_ENRICHMENT_PATHS],
                "minimum_gold_companies": MINIMUM_PUBLISHED_COMPANIES,
                "matched_terms": [],
                "padding_forbidden": True,
                "ranking_effect": "none",
            }
        ontology_complete_companies = [
            company for company in company_candidates if company.get("ontology_complete")
        ]
        gold_publishable = len(ontology_complete_companies) >= MINIMUM_PUBLISHED_COMPANIES
        published_companies = ontology_complete_companies if gold_publishable else []
        if published_companies:
            company_categories, published_companies = expand_value_chain(
                event_key,
                detected_category,
                published_companies,
            )
        else:
            company_categories = []
        publish_status = (
            "published"
            if gold_publishable
            else "excluded_by_context"
            if not company_eligible
            else "ontology_incomplete"
        )
        company_resolution = {
            "status": publish_status,
            "publish_status": publish_status,
            "candidate_count": len(company_candidates),
            "ontology_complete_count": len(ontology_complete_companies),
            "published_count": len(published_companies),
            "minimum_gold_companies": MINIMUM_PUBLISHED_COMPANIES,
            "score_independent_of_company_count": True,
            "direct_count": sum(company["strength"] == "direct" for company in company_candidates),
            "role_coverage": sorted({company["company_role"] for company in company_candidates}),
            "tier_counts": {
                tier: sum(company["relation_tier"] == tier for company in company_candidates)
                for tier in ("direct", "value_chain", "industry_watch")
            },
            "category_count": len(company_categories),
            "candidate_category_count": len(candidate_company_categories),
            "ontology_diagnostics": ontology_diagnostics,
            "reason": (
                "증거 온톨로지 경로가 완결된 고유 상장기업 3개 이상을 내부 Gold 후보층으로 보존"
                if gold_publishable
                else "사건·정책·논란 맥락은 기업 연결을 공개하지 않음"
                if not company_eligible
                else "완결된 증거 온톨로지 기업이 3개 미만이라 기업 Gold 후보층 공개를 보류"
            ),
        }
        display_name = representative_term
        display_name_policy = "observed_representative_term"
        canonical_name = str(event_resolution["canonical"] or "").strip()
        if re.fullmatch(r".+\s+대\s+.+", event_key) and event_key != representative_term:
            # Fixture query suffixes are still retained in raw_terms and
            # representative evidence, while the card title uses the compact
            # canonical event name shared by every source expression.
            display_name = event_key
            display_name_policy = "normalized_sports_fixture"
        if event_key in {"개기일식", "페르세우스 유성우"} and event_key != representative_term:
            # The source-backed event merge above is more specific than a bare
            # source token such as ``일식`` or ``페르세우스``. Raw expressions
            # remain available in raw_terms and representative_evidence.
            display_name = event_key
            display_name_policy = "source_context_event_merge"
        compact_representative = "".join(representative_term.split())
        if (
            len(compact_representative) == 6
            and compact_representative.isdigit()
            and canonical_name
            and canonical_name != representative_term
            and event_resolution["ground_truth_match"]
        ):
            # A six-digit stock code is still preserved as the observed term,
            # while a reviewed code-to-company identity is safer for the card
            # title than presenting an unexplained number. This never changes
            # event grouping, score, rank, or company relationship evidence.
            display_name = canonical_name
            display_name_policy = "reviewed_stock_code_to_company_name"
        broad_category = _broad_category(detected_category)
        category_label = _category_label(broad_category)
        keyword_status = (
            "ready"
            if len(keyword_items) == 5
            and all(keyword_fits_public_label(row.get("text")) for row in keyword_items)
            else "enrichment_pending"
        )
        candidates.append({
            "event_key": event_key,
            "topic": representative_term,
            "display_name": display_name,
            "observed_representative_term": representative_term,
            "display_name_policy": display_name_policy,
            "resolved_entity_name": event_resolution["canonical"],
            "representative_evidence": representative_evidence,
            "raw_terms": sorted({item["topic"] for item in observations}),
            "phenomenon_summary": phenomenon_summary,
            "context_status": context_status,
            "ground_truth_match": event_resolution["ground_truth_match"],
            "category": detected_category,
            "category_basis": category_basis,
            "broad_category": broad_category,
            "category_label": category_label,
            "category_ontology": category_ontology(detected_category),
            "trend_definition": _trend_definition(
                display_name,
                category_label,
                [item["text"] for item in keyword_items],
                ranking_contract["period_sources"],
            ),
            "disclaimer": "투자 추천이나 수익 예측이 아닙니다.",
            "lane": lane,
            "selection_reason": reason,
            "trend_fit": trend_fit,
            "selection_layer": selection_layer,
            "company_eligible": company_eligible,
            "score": score,
            "candidate_status": ranking_contract["candidate_status"],
            "is_current": ranking_contract["is_current"],
            "period_sources": ranking_contract["period_sources"],
            "freshness": ranking_contract["freshness"],
            "hours_since_last_seen": ranking_contract["hours_since_last_seen"],
            "previous_period_rank": ranking_contract["previous_period_rank"],
            "rank_change": ranking_contract["rank_change"],
            "rank_change_status": ranking_contract["rank_change_status"],
            "period_strength": round(current_signal, 6),
            "current_source_position": round(current_signal, 6),
            "momentum": round(momentum, 4), "persistence": round(persistence, 4),
            "momentum_delta": ranking_contract["signals"]["momentum_delta"],
            "score_components": score_components,
            "score_explanation": ranking_contract["score_explanation"],
            "source_metrics": ranking_contract["source_metrics"],
            "ranking_data_readiness": ranking_contract["data_readiness"],
            "lifecycle_baseline": lifecycle_baseline,
            "source_count": len(sources),
            "current_source_count": len(current_by_source),
            "source_badge": "교차출처" if len(sources) >= 2 else "단일출처",
            "latest_source_ranks": {
                source: item["source_rank"] for source, item in latest_by_source.items()
            },
            "rank_change_by_source": rank_changes,
            "source_rank_change": rank_changes,
            "first_seen_at": first_seen, "last_seen_at": last_seen, "age_hours": age_hours,
            "lifecycle": lifecycle, "lifecycle_reason": lifecycle_reason,
            "data_confidence": data_confidence,
            "verification_layer": verification_layer,
            "verification_signals": {
                **verification_layer,
                "ranking_effect": "none",
                "purpose": "public_spread_and_context_verification_only",
            },
            "news_context": {
                "status": "observed" if news_context_records else "not_linked",
                "claim_types": news_claim_types,
                "records": news_context_records,
                "affects_score": False,
                "ranking_source": False,
            },
            "context_research": context_research,
            "provenance": sorted({item["provenance"] for item in observations}),
            "series": [{"at": item["observed_at"], "source": item["source"],
                        "rank": item["source_rank"], "value": item["value"],
                        "provenance": item["provenance"],
                        "source_payload_json": item.get("source_payload_json"),
                        "related_terms_json": item.get("related_terms_json")}
                       for item in observations],
            "keywords": keyword_items,
            "related_keywords": keyword_items,
            "keyword_status": keyword_status,
            "keyword_evidence": {
                "total": len(keyword_items),
                "observed_source_count": sum(
                    item["status"] in {"observed_ranked_term", "observed_related_query"}
                    for item in keyword_items
                ),
                "reviewed_ontology_count": sum(
                    item["status"] in {
                        "approved_ontology_term",
                        "approved_ontology_related_term",
                    }
                    for item in keyword_items
                ),
                "candidate_count": 0,
                "status": "evidence_backed" if keyword_items else "insufficient",
                "reason": (
                    "동일 사건으로 묶인 관측 원문·Google 관련 검색어와 URL 근거를 검수한 온톨로지 용어만 표시"
                    if keyword_items
                    else "관측되거나 검수된 관련 표현이 없어 키워드를 비워 둠"
                ),
            },
            "companies": published_companies,
            "company_candidates": company_candidates,
            "company_categories": company_categories,
            "candidate_company_categories": candidate_company_categories,
            "company_resolution": company_resolution,
        })
    # Keep all monthly-hydrated identities available to period views, while
    # the public/top-level alias contains exactly the configured default
    # aggregate (24 hours for the live product).
    period_base_candidates = list(candidates)
    period_base_by_key = {item["event_key"]: item for item in period_base_candidates}
    candidates = [
        period_base_by_key[item["event_key"]]
        for item in default_ranking_contract["unified_ranking"]
    ]
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank
        item["observed_rank"] = rank
        item["home_rank"] = None
        item["rising_rank"] = None
        item["classification"] = {
            "issue": "이슈·주의",
            "main": "일반 트렌드",
            "review": "맥락 확인",
        }[item["lane"]]
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
    for item in candidates:
        item["main_rank"] = None
    for main_rank, item in enumerate(lanes["main"], 1):
        item["main_rank"] = main_rank
    evaluation_rows = []
    for item in candidates:
        expected = GROUND_TRUTH.get(item["event_key"])
        if expected:
            evaluation_rows.append({
                "display_name": item["display_name"],
                "category": item["category"],
                "ground_truth_expected": {"display_name": expected[0], "category": expected[1]},
            })
    home_gate_results = {
        item["event_key"]: _home_context_gate(item)
        for item in candidates
    }
    # The home list preserves observed score order but applies only automatic,
    # general product-fit and context rules. Enrichment readiness never changes
    # rank and a manual cache/whitelist is not consulted here.
    for item in candidates:
        _attach_keyword_company_links(item)
        home_allowed, home_reason = home_gate_results[item["event_key"]]
        item["home_context_status"] = "resolved" if home_allowed else "review_required"
        item["home_context_reason"] = home_reason
        item["home_eligible"] = bool(home_allowed)
        if item["lane"] == "main" and not home_allowed:
            item["selection_layer"] = "context_review_queue"

        unique_stocks = {
            str(company.get("stock_code") or "").strip()
            for company in item.get("companies") or []
            if str(company.get("stock_code") or "").strip()
        }
        company_published = (
            (item.get("company_resolution") or {}).get("publish_status") == "published"
            and len(unique_stocks) >= MINIMUM_FRONTEND_COMPANIES
        )
        if company_published:
            item["company_card_status"] = "ready"
            item["company_card_reason"] = "evidence_backed_ten_or_more"
        elif item.get("company_eligible"):
            item["company_card_status"] = "enrichment_pending"
            item["company_card_reason"] = "fewer_than_ten_evidence_backed_companies"
        else:
            item["company_card_status"] = "not_applicable"
            item["company_card_reason"] = "company_linking_not_allowed_for_lane_or_context"
        item["company_status"] = item["company_card_status"]

        keyword_rows = list(item.get("related_keywords") or item.get("keywords") or [])
        keyword_count = len(keyword_rows)
        keyword_lengths_valid = all(
            keyword_fits_public_label(row.get("text") if isinstance(row, dict) else row)
            for row in keyword_rows
        )
        complete_companies = []
        for company in item.get("companies") or []:
            evidence_urls = {
                str(source.get("url") or "").strip()
                for source in company.get("evidence_sources") or []
                if str(source.get("url") or "").strip()
            }
            if (
                str(company.get("company") or "").strip()
                and str(company.get("stock_code") or "").strip()
                and str(company.get("market") or "").strip()
                and str(company.get("company_description") or "").strip()
                and str(company.get("relationship_reason") or "").strip()
                and evidence_urls
                and company.get("ontology_complete") is True
            ):
                complete_companies.append(company)
        complete_company_count = len({
            str(company["stock_code"]).strip() for company in complete_companies
        })
        readiness_missing = []
        role_category_count = len({
            str(company.get("company_role_category") or "").strip()
            for company in complete_companies
            if str(company.get("company_role_category") or "").strip()
        })
        if item["keyword_status"] != "ready" or keyword_count != 5:
            readiness_missing.append("related_keywords_exactly_five")
        if not keyword_lengths_valid:
            readiness_missing.append("related_keywords_max_six_characters")
        if int(item.get("linked_keyword_count") or 0) < 2:
            readiness_missing.append("related_keywords_linked_to_companies_at_least_two")
        if (
            complete_company_count < MINIMUM_FRONTEND_COMPANIES
        ):
            readiness_missing.append("evidence_backed_listed_companies_at_least_ten")
        elif not public_company_role_count_is_valid(role_category_count):
            readiness_missing.append("company_role_categories_between_three_and_four")
        item["frontend_readiness_status"] = (
            "ready" if not readiness_missing else "enrichment_pending"
        )
        item["frontend_readiness_missing"] = readiness_missing
        item["frontend_keyword_count"] = keyword_count
        item["frontend_company_count"] = complete_company_count
        item["frontend_company_role_category_count"] = role_category_count
        item["publication_rank"] = None

    home_candidates = [
        item for item in candidates
        if item["lane"] == "main" and item["home_eligible"]
    ]
    apply_equal_platform_home_scores(home_candidates)
    home_candidates.sort(key=lambda item: (
        int(item.get("home_rank") or 10**9),
        str(item.get("event_key") or ""),
    ))

    completed_home_candidates = [
        item for item in home_candidates
        if item["frontend_readiness_status"] == "ready"
    ]
    rising_candidates = [
        item for item in completed_home_candidates
        if item.get("is_current") is True
        and (item.get("ranking_data_readiness") or {}).get("momentum_status") == "measured"
        and float(item.get("momentum_delta") or 0.0) > 0.0
    ]
    rising_candidates.sort(
        key=lambda item: (
            -float(item["momentum_delta"]),
            -float(item["period_strength"]),
            int(item["observed_rank"]),
            str(item["event_key"]),
        )
    )
    for rising_rank, item in enumerate(rising_candidates, 1):
        item["rising_rank"] = rising_rank

    home_top10 = select_balanced_home_top10(completed_home_candidates)
    rising_top10 = rising_candidates[:10]
    trend_top10 = list(home_top10)
    # Backwards-compatible alias for the existing frontend. It must remain
    # value-identical to ``home_top10`` during the migration period.
    public_top10 = list(home_top10)
    company_ready_trends = [
        item for item in home_candidates
        if int(item.get("frontend_company_count") or 0) >= MINIMUM_FRONTEND_COMPANIES
    ]
    category_summary = [
        {
            "category": category,
            "category_label": label,
            "observed_count": sum(
                item["broad_category"] == category for item in candidates
            ),
            "home_candidate_count": sum(
                item["broad_category"] == category for item in home_candidates
            ),
            "home_top10_count": sum(
                item["broad_category"] == category for item in home_top10
            ),
            "rising_top10_count": sum(
                item["broad_category"] == category for item in rising_top10
            ),
        }
        for category, label in PUBLIC_BROAD_CATEGORY_LABELS.items()
    ]
    ranking_periods, ranking_views = _build_period_views(
        period_ranking_contract,
        period_base_candidates,
        full_detail_event_keys={item["event_key"] for item in candidates},
    )
    change_metrics = _period_change_metrics(ranking_views)
    for item in candidates:
        item["attention_change"] = change_metrics.get(item["event_key"], {
            "24h": {"status": "unavailable", "percent": None, "basis": "previous_equal_period_score"},
            "7d": {"status": "unavailable", "percent": None, "basis": "previous_equal_period_score"},
        })
    _attach_frontend_story(candidates)
    default_view = ranking_views[period_ranking_contract["default_period"]]
    if [item["event_key"] for item in default_view["unified_ranking"]] != [
        item["event_key"] for item in candidates
    ] or [item["score"] for item in default_view["unified_ranking"]] != [
        item["score"] for item in candidates
    ]:
        raise ValueError("top-level ranking must remain the hydrated default-period alias")
    if [item["event_key"] for item in default_view["period_top10"]] != [
        item["event_key"] for item in trend_top10
    ]:
        raise ValueError("top-level trend_top10 must remain the hydrated default-period alias")
    context_resolved_candidates = list(home_candidates)
    home_status = (
        "complete" if len(home_top10) == 10
        else "partial" if home_top10
        else "empty"
    )
    publication_readiness = {
        "policy_version": "complete-home-contract-v2",
        "target_count": 10,
        "ready_count": len(completed_home_candidates),
        "published_count": len(home_top10),
        "pending_count": len(home_candidates) - len(completed_home_candidates),
        "publication_ready": bool(home_top10),
        "home_status": home_status,
        "required_keyword_count": 5,
        "minimum_company_count": MINIMUM_FRONTEND_COMPANIES,
        "padding_forbidden": True,
        "ranking_effect": "none",
        "rule": (
            "Only product-fit trends with a concrete current trigger, exactly five "
            "sourced keywords, and ten complete listed-company relations across two "
            "to four role categories may enter frontend Top10 arrays. One to nine "
            "completed cards are published as partial; padding is forbidden."
        ),
    }
    home_quality_gate = {
        "policy_version": "home-trend-subset-v4",
        "ranking_effect": "none",
        "unified_ranking_preserved": True,
        "main_lane_total": len(lanes["main"]),
        "trend_top10_count": len(trend_top10),
        "company_count_affects_home": False,
        "minimum_published_companies": MINIMUM_FRONTEND_COMPANIES,
        "home_eligible_total": len(home_candidates),
        "home_excluded_total": len(lanes["main"]) - len(home_candidates),
        "exclusion_reasons": dict(sorted(Counter(
            home_gate_results[item["event_key"]][1]
            for item in lanes["main"]
            if not home_gate_results[item["event_key"]][0]
        ).items())),
        "context_resolved_total": len(context_resolved_candidates),
        "context_review_total": len(lanes["main"]) - len(context_resolved_candidates),
        "context_review_reasons": dict(sorted(Counter(
            item.get("home_context_reason") or "context_unresolved"
            for item in lanes["main"]
            if item.get("home_context_status") != "resolved"
        ).items())),
        "rule": (
            "자동 제품 적합·맥락 규칙을 통과한 main 후보 중 맥락·키워드·기업 "
            "계약까지 완성된 항목만 다중 출처 홈 순위로 공개함; 미완성 후보는 "
            "전체 실측 순위와 보강 큐에는 남지만 홈 카드에 채우기용으로 쓰지 않음"
        ),
    }
    ontology_enrichment_queue = [
        {
            "rank": item["rank"],
            "event_key": item["event_key"],
            "representative_term": item["display_name"],
            "observed_terms": [item["display_name"], *[keyword["text"] for keyword in item["keywords"]]],
            "evidence_backed_company_count": item["company_resolution"]["candidate_count"],
            # The queue serves the frontend contract, which is stricter than
            # the ontology Gold publication floor. Report the actual ten-
            # company completion target so operators do not stop early.
            "minimum_required": MINIMUM_FRONTEND_COMPANIES,
            "missing_company_paths": max(
                0,
                MINIMUM_FRONTEND_COMPANIES - item["company_resolution"]["candidate_count"],
            ),
            "status": "evidence_research_required",
            "lookup_status": (
                "reviewed_match_below_gold_gate"
                if item["company_resolution"]["candidate_count"]
                else "no_reviewed_ontology_match"
            ),
            "research_stages": [
                "representative_or_related_term_lookup",
                "entity_product_or_industry_bridge",
                "company_relationship_evidence",
                "listed_stock_identity_evidence",
                "team_review",
            ],
            "allowed_evidence": ["company_official", "regulatory_filing", "reputable_news", "reviewed_industry_structure"],
            "padding_forbidden": True,
            "affects_score": False,
        }
        for item in lanes["main"]
        if item["frontend_readiness_status"] != "ready"
    ]

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
    expected_rank_sources = {"x", "google_trends"}
    missing_current_sources = sorted(expected_rank_sources - current_available_sources)
    if not current_available_sources:
        ranking_availability = {
            "status": "unavailable",
            "label": "현재 순위 없음",
            "is_combined_rank": False,
            "current_sources": [],
            "missing_sources": sorted(expected_rank_sources),
            "reason": "현재 시간에 품질 게이트를 통과한 X·Google 원장이 없음",
        }
    elif missing_current_sources:
        ranking_availability = {
            "status": "provisional_single_source",
            "label": "단일출처 잠정 순위",
            "is_combined_rank": False,
            "current_sources": sorted(current_available_sources),
            "missing_sources": missing_current_sources,
            "reason": "X와 Google 중 한 출처만 현재 시간에 관측되어 통합 순위로 확정할 수 없음",
        }
    elif eligible_hour_count < MVP_HISTORY_HOURS:
        ranking_availability = {
            "status": "provisional_history",
            "label": "양출처 잠정 순위",
            "is_combined_rank": True,
            "current_sources": sorted(current_available_sources),
            "missing_sources": [],
            "reason": "X·Google은 모두 관측됐지만 24시간 MVP 이력이 아직 부족함",
        }
    else:
        ranking_availability = {
            "status": "mature_combined",
            "label": "양출처 24시간 순위",
            "is_combined_rank": True,
            "current_sources": sorted(current_available_sources),
            "missing_sources": [],
            "reason": "X·Google 현재 관측과 최근 24시간 MVP 원장 기준 충족",
        }

    for item in candidates:
        item["ranking_availability_status"] = ranking_availability["status"]

    return {
        "schema_version": "trzip-intelligence-v3",
        "mode": "live",
        "is_live": True,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "hours": hours},
        "sources": ["x", "google_trends"],
        "ranking_availability": ranking_availability,
        "ranking_data_readiness": ranking_v2["data_readiness"],
        "score_formula": (
            "35% current attention strength + 25% measured rising velocity + "
            "20% X-Google source breadth + 10% window persistence + "
            "10% last-seen recency"
        ),
        "score_policy": {
            "formula_version": ranking_v2["formula_version"],
            "source_values_used": False,
            "period_strength": (
                "per-source 0..1 positions aggregated as 70% recency-weighted mean + 30% peak"
            ),
            "momentum": (
                "previous equal-length period when covered, otherwise first-half to second-half; "
                "each side requires at least three snapshots; unavailable comparison scores zero"
            ),
            "missing_comparison_policy": "unavailable_zero_points_no_rising_rank",
            "persistence": "equal-source observed snapshot count divided by the full selected window",
            "recency": "last-seen exponential decay with half-life equal to half the selected period",
            "lifecycle_baseline": "60-day observed baseline; ranking_effect=none",
            "company_count_affects_rank": False,
            "future_rows_used": False,
            "active_candidate_gate": "observed in the selected 24h, 7d, or 30d period",
            "candidate_status": "is_current or period_observed; stale items retain last_seen and freshness",
            "default_period": "daily",
            "canonical_observed_rank_sources": ["x", "google_trends"],
            "home_rank_policy": HOME_SOURCE_POLICY_VERSION,
            "home_rank_inputs": ["x", "google_trends"],
            "optional_home_input_policy": "disabled; verification sources cannot alter selection score or order",
        },
        "home_quality_gate": home_quality_gate,
        "publication_readiness": publication_readiness,
        "context_evidence_policy": {
            "news_is_ranking_source": False,
            "news_layers": ["context", "company_evidence"],
            "promotion_gate": "NAVER 뉴스는 맥락 근거를 완성할 수 있지만 X·Google 점수·정렬·적격성은 변경하지 않음",
            "context_affects_score": False,
        },
        "verification_policy": {
            "active_platforms": ["naver_news"],
            "disabled_platforms": [
                "youtube",
                "instagram",
                "naver_blog",
                "naver_search_trend",
            ],
            "storage": "provider_verification_ledger_sqlite",
            "unavailable_platform_penalty": 0,
            "verification_affects_score": False,
        },
        "hourly_rankings": hourly_ranking,
        "daily_aggregates": daily_aggregates,
        "normalization_evaluation": evaluate_resolution(evaluation_rows),
        "ranking_default_period": period_ranking_contract["default_period"],
        "ranking_periods": ranking_periods,
        "ranking_views": ranking_views,
        "ranking_top_level_alias": {
            "period": "daily",
            "unified_ranking": "daily_period_aggregate",
            "trend_top10": "daily_home_top10",
        },
        "unified_ranking": candidates,
        "all_observed_ranking": candidates,
        "home_status": home_status,
        "home_top10": home_top10,
        "rising_top10": rising_top10,
        "category_summary": category_summary,
        "trend_top10": trend_top10,
        "public_top10": public_top10,
        "company_ready_trends": company_ready_trends,
        "ontology_enrichment_queue": ontology_enrichment_queue,
        "quality_summary": {
            "total_ranked_candidates": len(candidates),
            "main_candidates": len(lanes["main"]),
            "public_eligible_candidates": len(home_candidates),
            "resolved_public_candidates": len(context_resolved_candidates),
            "excluded_from_public_due_to_context": (
                len(home_candidates) - len(context_resolved_candidates)
            ),
            "review_required_in_public_top10": sum(
                item["home_context_status"] == "review_required" for item in public_top10
            ),
            "public_top10_count": len(public_top10),
            "frontend_complete_candidate_count": len(completed_home_candidates),
            "frontend_publication_ready": publication_readiness["publication_ready"],
            "home_status": home_status,
            "trend_top10_count": len(trend_top10),
            "company_ready_trend_count": len(company_ready_trends),
            "excluded_from_public_due_to_non_main_lane": len(candidates) - len(home_candidates),
            "top10_with_five_keywords": sum(
                len(item["keywords"]) == 5
                for item in public_top10
            ),
            "top10_with_company_mapping": sum(bool(item["companies"]) for item in public_top10),
            "top10_without_forced_company": sum(not item["companies"] for item in public_top10),
            "top10_low_confidence": sum(
                item["data_confidence"]["level"] in {"low", "very_low"}
                for item in public_top10
            ),
            "eligible_ledger_hours": eligible_hour_count,
            "current_available_sources": sorted(current_available_sources),
            "missing_current_sources": missing_current_sources,
            "ranking_availability_status": ranking_availability["status"],
            "ranking_maturity_status": (
                "mature" if eligible_hour_count >= MVP_HISTORY_HOURS else "provisional"
            ),
            "history_stage": history_stage(eligible_hour_count),
            "mvp_required_history_hours": MVP_HISTORY_HOURS,
            "operational_target_history_hours": OPERATIONAL_HISTORY_TARGET_HOURS,
            "long_horizon_history_hours": LONG_HORIZON_HISTORY_HOURS,
            "quarantined_source_hour_count": len(quarantined_source_hours),
            "quarantined_source_hours": quarantined_source_hours,
            "source_snapshot_quality": snapshot_quality,
        },
        "lanes": lanes,
    }
    payload["presentation_feed"] = build_presentation_feed(payload)
    return payload
