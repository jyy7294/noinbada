"""A bounded, source-faithful X-only trend preview.

This is deliberately separate from the multi-source live publication.  It is
useful for checking whether the X Korea trend board alone contains concrete
trend candidates, without silently substituting Google, news, a hand-picked
seed, or generated enrichment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


POLICY_VERSION = "x-only-source-preview-v1"
_SAFETY_MARKERS = (
    "대통령", "국회", "체포", "피해자", "살인", "사망", "탄핵", "선거",
    "성범죄", "구속", "미사일", "president", "arrest",
)
_CONCRETE_EVENT_MARKERS = (
    "팬미팅", "상영회", "팝마트", "챌린", "fanmeeting", "screening", "popmart", "challenge",
)
_CONCRETE_ENTITY_MARKERS = (
    "팀리그", "아시안 게임", "어워드", "다이내믹스", "사발면", "미스트롯",
    "오디세이", "openai", "grok", "리니지", "spotify",
)
_GENERIC_MARKERS = (
    "먹기 시작", "귀인지", "선예매 인증", "독립운동가", "대통령제",
    "국회 권한", "커미션 모금", "폭풍 잔소리",
)


def _parse_timestamp(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("x payload must contain an ISO-8601 observed_at") from error
    if parsed.tzinfo is None:
        raise ValueError("x payload observed_at must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


def _validate(payload: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
    if payload.get("source") != source or payload.get("region") != "KR":
        raise ValueError(f"{source}-only preview requires a Korea source payload")
    if payload.get("region_verified") is not True:
        raise ValueError("x-only preview requires verified Korea region")
    trends = payload.get("trends")
    expected_count = int(payload.get("row_count") or 0)
    if not isinstance(trends, list) or expected_count <= 0 or len(trends) != expected_count:
        raise ValueError("source-only preview requires complete declared source trends")
    ranks = [item.get("rank") for item in trends if isinstance(item, dict)]
    if sorted(ranks) != list(range(1, expected_count + 1)):
        raise ValueError("source-only preview requires contiguous unique source ranks")
    if any(not str(item.get("topic") or "").strip() for item in trends):
        raise ValueError("x-only preview requires a topic at every source rank")
    _parse_timestamp(payload.get("observed_at"))
    return sorted(trends, key=lambda item: int(item["rank"]))


def _decision(topic: str) -> tuple[str, str]:
    normalized = " ".join(topic.strip().split())
    lowered = normalized.casefold()
    if any(marker.casefold() in lowered for marker in _SAFETY_MARKERS):
        return "excluded", "safety_or_political_issue"
    if normalized.startswith("#"):
        return "review", "hashtag_campaign_without_specific_event_context"
    if any(marker.casefold() in lowered for marker in _GENERIC_MARKERS):
        return "review", "generic_or_contextless_expression"
    if any(marker.casefold() in lowered for marker in _CONCRETE_EVENT_MARKERS):
        return "candidate", "concrete_event_or_consumer_signal"
    if any(marker.casefold() in lowered for marker in _CONCRETE_ENTITY_MARKERS):
        return "candidate", "concrete_content_product_or_technology_signal"
    if len(lowered) <= 3:
        return "review", "expression_too_short_or_ambiguous"
    return "review", "needs_context_resolution"


def classify_source_topic(topic: str) -> tuple[str, str]:
    """Public, score-free first-pass classification for an observed expression."""

    return _decision(topic)


def build_source_only_preview(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Return an auditable single-source card feed without invented enrichment."""

    trends = _validate(payload, source=source)
    evaluated: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for trend in trends:
        rank = int(trend["rank"])
        topic = " ".join(str(trend["topic"]).strip().split())
        decision, reason = _decision(topic)
        row = {"source_rank": rank, "topic": topic, "decision": decision, "reason": reason}
        evaluated.append(row)
        if decision == "candidate":
            cards.append({
                "display_name": topic,
                "flow_group": f"newly_observed_on_{source}",
                "platform_observation_summary": {
                    "x": {"observed": source == "x", "latest_rank": rank if source == "x" else None, "ranking_input": source == "x"},
                    "google_trends": {"observed": source == "google_trends", "latest_rank": rank if source == "google_trends" else None, "ranking_input": source == "google_trends"},
                    "naver_news": {"observed": False, "selection_input": False},
                },
                "data_status": f"{source}_source_only",
                "next_gate": "news_context_keywords_and_companies_required",
            })

    counts = {key: sum(row["decision"] == key for row in evaluated) for key in ("candidate", "review", "excluded")}
    feed = {
        "status": "ready" if cards else "empty",
        "cards": cards,
        "card_count": len(cards),
        "top_limit": 10,
        "note": "Cards are single-source candidates; no external context, keywords, or company relationship is inferred.",
    }
    return {
        "schema_version": "trzip-single-source-preview-v1",
        "policy_version": f"{POLICY_VERSION}:{source}",
        "observed_at": _parse_timestamp(payload["observed_at"]),
        "source_receipt": {
            "source": source, "region": "KR", "region_verified": True,
            "collector": payload.get("collector"), "row_count": len(trends),
        },
        "source_only_feed": feed,
        "source_audit": {"all_x_trends": evaluated, "counts": counts},
    }


def build_x_only_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper for the X-only preview."""

    return build_source_only_preview(payload, source="x")
