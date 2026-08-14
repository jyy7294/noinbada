from __future__ import annotations

import pytest

from trzip.combined_source_ranking import build_combined_ranking, select_diverse_top10
from trzip.event_resolution import normalize_event_key


def _event(name: str, *, category: str = "content", hours: int = 6, rank: int = 3) -> dict:
    return {
        "canonical_name": name,
        "broad_category": category,
        "observed_hours": hours,
        "best_source_rank": rank,
        "latest_source_rank": rank,
        "first_observed_at": "2026-08-14T01:00:00+00:00",
        "last_observed_at": "2026-08-14T07:00:00+00:00",
        "is_current": True,
        "source_expressions": [name],
        "raw_terms": [name],
    }


def _document(source: str, events: list[dict]) -> dict:
    return {
        "source": source,
        "window": {
            "from": "2026-08-12T07:00:00+00:00",
            "to": "2026-08-14T07:00:00+00:00",
            "hours": 48,
        },
        "valid_snapshots": 12,
        "observed_source_rows": 360 if source == "x" else 2400,
        "all_final_topics": [
            {"best_source_rank": 30 if source == "x" else 200},
            *({"best_source_rank": event["best_source_rank"]} for event in events),
        ],
        "included_flow_candidates": events,
    }


def test_cross_source_event_gets_explicit_bonus_and_is_merged_once():
    shared_x = _event("공통 작품")
    shared_google = _event("공통 작품")
    x_only = _event("X 단독 작품")
    result = build_combined_ranking(
        _document("x", [shared_x, x_only]),
        _document("google_trends", [shared_google]),
    )
    assert result["combined_event_count"] == 2
    assert result["cross_source_event_count"] == 1
    assert result["combined_ranking"][0]["canonical_name"] == "공통 작품"
    assert result["combined_ranking"][0]["cross_source_bonus"] == 12.0
    assert result["combined_ranking"][1]["cross_source_bonus"] == 0.0


def test_single_source_events_remain_rankable_with_missing_source_as_zero():
    result = build_combined_ranking(
        _document("x", [_event("X 단독", hours=10, rank=1)]),
        _document("google_trends", [_event("Google 단독", hours=4, rank=80)]),
    )
    assert {item["canonical_name"] for item in result["combined_ranking"]} == {"X 단독", "Google 단독"}
    x_item = next(item for item in result["combined_ranking"] if item["canonical_name"] == "X 단독")
    assert set(x_item["observed_sources"]) == {"x"}
    assert x_item["combined_score"] == pytest.approx(
        0.44 * x_item["source_details"]["x"]["metrics"]["score"],
        abs=1e-4,
    )


def test_category_conflict_fails_closed_instead_of_silently_merging():
    with pytest.raises(ValueError, match="category conflict"):
        build_combined_ranking(
            _document("x", [_event("같은 사건", category="culture")]),
            _document("google_trends", [_event("같은 사건", category="content")]),
        )


def test_home_top10_preserves_scores_but_caps_category_and_respects_exclusions():
    ranking = []
    categories = ["sports"] * 7 + ["culture", "food", "content", "technology", "consumer", "market"]
    for index, category in enumerate(categories, start=1):
        ranking.append({
            "canonical_name": f"event-{index}",
            "normalized_event_key": normalize_event_key(f"event-{index}"),
            "broad_category": category,
            "combined_rank": index,
            "combined_score": 100 - index,
        })
    selected, audit = select_diverse_top10(
        ranking,
        excluded_names=("event-8",),
        limit=10,
        max_per_category=3,
        minimum_categories=6,
    )
    assert all(item["canonical_name"] != "event-8" for item in selected)
    assert len({item["broad_category"] for item in selected}) >= 6
    assert max(
        sum(item["broad_category"] == category for item in selected)
        for category in {item["broad_category"] for item in selected}
    ) <= 3
    assert audit[0]["canonical_name"] == "event-8"
    assert all(item["combined_score"] == 100 - item["combined_rank"] for item in selected)
