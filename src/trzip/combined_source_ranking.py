"""Deterministic X + Google ranking for adjudicated source events.

This module consumes the exhaustive source-only adjudication outputs.  It does
not decide whether an expression is a trend and it never uses enrichment data.
Its only job is to put already-included X and Google events on one comparable
scale, merge identical canonical events, and award a transparent cross-source
bonus.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from trzip.event_resolution import normalize_event_key


POLICY_VERSION = "combined-source-ranking-v1"
SOURCE_SCORE_WEIGHTS = {
    "persistence": 0.45,
    "position": 0.35,
    "recency": 0.20,
}
COMBINED_WEIGHTS = {
    "x": 0.44,
    "google_trends": 0.44,
    "cross_source_bonus": 12.0,
}


def _parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ranking timestamps must include timezone")
    return parsed.astimezone(UTC)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _source_score(
    event: dict,
    *,
    valid_snapshots: int,
    rank_ceiling: int,
    window_end: datetime,
    recency_half_life_hours: float,
) -> dict:
    if valid_snapshots <= 0:
        raise ValueError("valid_snapshots must be positive")
    if rank_ceiling <= 0:
        raise ValueError("rank_ceiling must be positive")
    persistence = _clamp01(float(event["observed_hours"]) / valid_snapshots)
    if rank_ceiling == 1:
        position = 1.0
    else:
        position = 1.0 - ((float(event["best_source_rank"]) - 1.0) / (rank_ceiling - 1.0))
    position = _clamp01(position)
    last_observed_at = _parse_at(event["last_observed_at"])
    age_hours = max(0.0, (window_end - last_observed_at).total_seconds() / 3600.0)
    recency = math.exp(-math.log(2.0) * age_hours / recency_half_life_hours)
    recency = _clamp01(recency)
    total = 100.0 * (
        SOURCE_SCORE_WEIGHTS["persistence"] * persistence
        + SOURCE_SCORE_WEIGHTS["position"] * position
        + SOURCE_SCORE_WEIGHTS["recency"] * recency
    )
    return {
        "score": round(total, 4),
        "persistence": round(persistence, 6),
        "position": round(position, 6),
        "recency": round(recency, 6),
        "age_hours": round(age_hours, 4),
        "observed_hours": int(event["observed_hours"]),
        "valid_snapshots": int(valid_snapshots),
        "best_source_rank": int(event["best_source_rank"]),
        "latest_source_rank": event.get("latest_source_rank"),
        "rank_ceiling": int(rank_ceiling),
        "first_observed_at": event["first_observed_at"],
        "last_observed_at": event["last_observed_at"],
        "is_current": bool(event.get("is_current")),
    }


def select_diverse_top10(
    ranking: list[dict],
    *,
    excluded_names: tuple[str, ...] = (),
    limit: int = 10,
    max_per_category: int = 3,
    minimum_categories: int = 6,
) -> tuple[list[dict], list[dict]]:
    """Select a varied home list without changing canonical scores or ranks."""

    excluded = {normalize_event_key(name) for name in excluded_names}
    eligible = [item for item in ranking if item["normalized_event_key"] not in excluded]
    selected: list[dict] = []
    category_counts: dict[str, int] = {}
    for item in eligible:
        category = item["broad_category"]
        if category_counts.get(category, 0) >= max_per_category:
            continue
        selected.append(item)
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(selected) == limit:
            break

    available_categories = {item["broad_category"] for item in eligible}
    target_categories = min(minimum_categories, limit, len(available_categories))
    selected_keys = {item["normalized_event_key"] for item in selected}
    while len({item["broad_category"] for item in selected}) < target_categories:
        present = {item["broad_category"] for item in selected}
        replacement = next(
            (
                item for item in eligible
                if item["normalized_event_key"] not in selected_keys
                and item["broad_category"] not in present
            ),
            None,
        )
        if replacement is None:
            break
        replace_index = next(
            (
                index for index in range(len(selected) - 1, -1, -1)
                if sum(
                    candidate["broad_category"] == selected[index]["broad_category"]
                    for candidate in selected
                ) > 1
            ),
            None,
        )
        if replace_index is None:
            break
        selected_keys.remove(selected[replace_index]["normalized_event_key"])
        selected[replace_index] = replacement
        selected_keys.add(replacement["normalized_event_key"])

    selected.sort(key=lambda item: item["combined_rank"])
    home_items: list[dict] = []
    for home_rank, item in enumerate(selected, start=1):
        home_items.append({**item, "home_rank": home_rank})
    excluded_audit = [
        {
            "canonical_name": item["canonical_name"],
            "combined_rank": item["combined_rank"],
            "combined_score": item["combined_score"],
            "reason_code": "excluded_from_home_by_context_quality_feedback",
        }
        for item in ranking
        if item["normalized_event_key"] in excluded
    ]
    return home_items, excluded_audit


def build_combined_ranking(
    x_document: dict,
    google_document: dict,
    *,
    home_excluded_names: tuple[str, ...] = (),
) -> dict:
    documents = {"x": x_document, "google_trends": google_document}
    expected_sources = set(documents)
    if {document.get("source") for document in documents.values()} != expected_sources:
        raise ValueError("documents must contain one x and one google_trends source")

    window_ends = {_parse_at(document["window"]["to"]) for document in documents.values()}
    if len(window_ends) != 1:
        raise ValueError("source documents must use the same window end")
    window_hours = {int(document["window"]["hours"]) for document in documents.values()}
    if len(window_hours) != 1:
        raise ValueError("source documents must use the same window length")
    window_end = next(iter(window_ends))
    hours = next(iter(window_hours))
    half_life = max(1.0, hours / 2.0)

    source_context: dict[str, dict] = {}
    for source, document in documents.items():
        all_topics = document.get("all_final_topics") or []
        rank_ceiling = max((int(item["best_source_rank"]) for item in all_topics), default=30 if source == "x" else 1)
        source_context[source] = {
            "valid_snapshots": int(document["valid_snapshots"]),
            "rank_ceiling": rank_ceiling,
            "observed_source_rows": int(document["observed_source_rows"]),
        }

    events: dict[str, dict] = {}
    for source, document in documents.items():
        context = source_context[source]
        for item in document.get("included_flow_candidates") or []:
            canonical_name = " ".join(str(item["canonical_name"]).split())
            canonical_key = normalize_event_key(canonical_name)
            event = events.setdefault(canonical_key, {
                "canonical_name": canonical_name,
                "normalized_event_key": canonical_key,
                "broad_category": item["broad_category"],
                "sources": {},
            })
            if event["broad_category"] != item["broad_category"]:
                raise ValueError(f"category conflict for cross-source event: {canonical_name}")
            if source in event["sources"]:
                raise ValueError(f"duplicate canonical event inside {source}: {canonical_name}")
            event["sources"][source] = {
                "metrics": _source_score(
                    item,
                    valid_snapshots=context["valid_snapshots"],
                    rank_ceiling=context["rank_ceiling"],
                    window_end=window_end,
                    recency_half_life_hours=half_life,
                ),
                "source_expressions": item.get("source_expressions") or [],
                "raw_terms": item.get("raw_terms") or [],
            }

    ranked: list[dict] = []
    for event in events.values():
        x_score = event["sources"].get("x", {}).get("metrics", {}).get("score", 0.0)
        google_score = event["sources"].get("google_trends", {}).get("metrics", {}).get("score", 0.0)
        cross_source = len(event["sources"]) == 2
        overlap_bonus = COMBINED_WEIGHTS["cross_source_bonus"] if cross_source else 0.0
        combined_score = (
            COMBINED_WEIGHTS["x"] * x_score
            + COMBINED_WEIGHTS["google_trends"] * google_score
            + overlap_bonus
        )
        ranked.append({
            "canonical_name": event["canonical_name"],
            "normalized_event_key": event["normalized_event_key"],
            "broad_category": event["broad_category"],
            "combined_score": round(combined_score, 4),
            "cross_source_observed": cross_source,
            "cross_source_bonus": overlap_bonus,
            "observed_sources": sorted(event["sources"]),
            "source_count": len(event["sources"]),
            "is_current": any(value["metrics"]["is_current"] for value in event["sources"].values()),
            "source_details": event["sources"],
            "ranking_effect_from_enrichment": "none",
        })

    ranked.sort(key=lambda item: (
        -item["combined_score"],
        -int(item["cross_source_observed"]),
        -sum(value["metrics"]["observed_hours"] for value in item["source_details"].values()),
        item["canonical_name"].casefold(),
    ))
    for rank, item in enumerate(ranked, start=1):
        item["combined_rank"] = rank

    diverse_top10, home_exclusion_audit = select_diverse_top10(
        ranked,
        excluded_names=home_excluded_names,
    )

    return {
        "schema_version": "trzip-combined-source-ranking-v1",
        "policy_version": POLICY_VERSION,
        "window": {
            "from": x_document["window"]["from"],
            "to": x_document["window"]["to"],
            "hours": hours,
        },
        "method": {
            "source_score": "100 * (0.45*persistence + 0.35*position + 0.20*recency)",
            "combined_score": "0.44*x_score + 0.44*google_score + 12*cross_source_observed",
            "source_score_weights": SOURCE_SCORE_WEIGHTS,
            "combined_weights": COMBINED_WEIGHTS,
            "recency_half_life_hours": half_life,
            "missing_source_score": 0,
            "tie_break": ["combined_score", "cross_source_observed", "total_observed_hours", "canonical_name"],
            "enrichment_or_manual_rank_effect": "none",
        },
        "home_selection_policy": {
            "limit": 10,
            "max_per_category": 3,
            "minimum_categories_when_available": 6,
            "canonical_rank_and_score_preserved": True,
            "excluded_names_affect_home_only": True,
        },
        "source_status": source_context,
        "cross_source_event_count": sum(item["cross_source_observed"] for item in ranked),
        "combined_event_count": len(ranked),
        "raw_score_top10": ranked[:10],
        "home_exclusion_audit": home_exclusion_audit,
        "top10": diverse_top10,
        "combined_ranking": ranked,
    }
