from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trzip.ranking_v2 import (
    DEFAULT_RANKING_PERIOD,
    FORMULA_VERSION,
    build_period_rankings_v2,
    build_ranking_v2,
    classify_lifecycle_v2,
    normalize_source_position,
)


AT = datetime(2026, 8, 13, 3, tzinfo=UTC)


def _row(
    stamp: datetime,
    source: str,
    event_key: str,
    rank: int,
    *,
    provenance: str = "observed",
) -> dict:
    return {
        "observed_at": stamp.isoformat(),
        "source": source,
        "event_key": event_key,
        "source_rank": rank,
        "provenance": provenance,
        "quality_status": "eligible",
    }


def _snapshot(stamp: datetime, source: str, *events: str) -> list[dict]:
    return [_row(stamp, source, event, rank) for rank, event in enumerate(events, 1)]


def _event(result: dict, event_key: str = "target") -> dict:
    return next(item for item in result["ranking"] if item["event_key"] == event_key)


def test_source_position_is_comparable_across_different_list_lengths():
    assert normalize_source_position(1, 30) == 1.0
    assert normalize_source_position(1, 200) == 1.0
    assert normalize_source_position(30, 30) == 0.0
    assert normalize_source_position(200, 200) == 0.0
    assert normalize_source_position(15, 30) == pytest.approx(15 / 29)


def test_cross_source_advantage_is_exactly_the_visible_five_points():
    single_rows = [
        *_snapshot(AT, "x", "target", "x filler"),
        *_snapshot(AT, "google_trends", "google filler"),
    ]
    dual_rows = [
        *_snapshot(AT, "x", "target", "x filler"),
        *_snapshot(AT, "google_trends", "target", "google filler"),
    ]

    single = _event(build_ranking_v2(single_rows, at=AT))
    dual = _event(build_ranking_v2(dual_rows, at=AT))

    assert single["signals"]["current"] == dual["signals"]["current"] == 1.0
    assert single["score_components"]["cross_source_points"] == 0.0
    assert dual["score_components"]["cross_source_points"] == 5.0
    assert dual["score"] - single["score"] == 5.0


def test_missing_exact_previous_hour_uses_neutral_momentum_not_older_snapshot():
    rows = [
        *_snapshot(AT - timedelta(hours=2), "x", "target", "old filler"),
        *_snapshot(AT, "x", "target", "current filler"),
    ]

    item = _event(build_ranking_v2(rows, at=AT))

    assert item["score_components"]["momentum_points"] == 10.0
    assert item["signals"]["momentum_delta"] is None
    assert item["data_readiness"]["momentum"] == {
        "status": "unavailable_neutral",
        "neutral_applied": True,
        "comparable_sources": [],
        "unavailable_sources": ["x"],
    }


def test_present_previous_snapshot_can_measure_a_new_entry():
    rows = [
        *_snapshot(AT - timedelta(hours=1), "x", "other", "old filler"),
        *_snapshot(AT, "x", "target", "current filler"),
    ]

    item = _event(build_ranking_v2(rows, at=AT))

    assert item["signals"]["momentum_delta"] == 1.0
    assert item["score_components"]["momentum_points"] == 20.0
    assert item["data_readiness"]["momentum"]["status"] == "ready"


def test_persistence_denominator_is_source_specific_not_union_of_all_hours():
    x_rows: list[dict] = []
    for age in range(4):
        x_rows += _snapshot(AT - timedelta(hours=age), "x", "target", f"x filler {age}")
    # Both datasets have a current Google snapshot.  The second only adds a
    # long Google history; it must not dilute an X-only event's persistence.
    base = [*x_rows, *_snapshot(AT, "google_trends", "g current")]
    with_google_history = list(base)
    for age in range(1, 97):
        with_google_history += _snapshot(
            AT - timedelta(hours=age), "google_trends", f"g filler {age}"
        )

    base_item = _event(build_ranking_v2(base, at=AT))
    history_item = _event(build_ranking_v2(with_google_history, at=AT))

    assert base_item["source_metrics"]["persistence"]["x"] == {
        "eligible_hours": 4,
        "observed_hours": 4,
        "presence_rate": 1.0,
        "maturity": round(4 / 96, 6),
        "adjusted_signal": round(4 / 96, 6),
    }
    assert (
        base_item["score_components"]["persistence_points"]
        == history_item["score_components"]["persistence_points"]
    )


def test_historical_evidence_loses_influence_with_exponential_age_decay():
    current = _snapshot(AT, "x", "target", "current filler")
    recent_rows = [
        *current,
        *_snapshot(AT - timedelta(hours=1), "x", "target", "recent filler"),
    ]
    old_rows = [
        *current,
        *_snapshot(AT - timedelta(hours=48), "x", "target", "old filler"),
    ]

    recent = _event(build_ranking_v2(recent_rows, at=AT))
    old = _event(build_ranking_v2(old_rows, at=AT))

    assert recent["score_components"]["decayed_history_points"] > old[
        "score_components"
    ]["decayed_history_points"]
    assert recent["source_metrics"]["decayed_history"]["x"][
        "weighted_evidence"
    ] > old["source_metrics"]["decayed_history"]["x"]["weighted_evidence"]


def test_sixty_day_baseline_changes_lifecycle_but_never_score():
    current_rows = _snapshot(AT, "x", "target", "current filler")
    returning_rows = [
        *current_rows,
        *_snapshot(AT - timedelta(days=30), "x", "target", "baseline filler"),
    ]

    new = _event(build_ranking_v2(current_rows, at=AT))
    returning = _event(build_ranking_v2(returning_rows, at=AT))

    assert new["score"] == returning["score"]
    assert new["lifecycle"]["state"] == "new"
    assert returning["lifecycle"]["state"] == "rebounding"
    assert returning["lifecycle_baseline"]["window_days"] == 60
    assert returning["lifecycle_baseline"]["ranking_effect"] == "none"
    assert returning["score_explanation"]["lifecycle_baseline_ranking_effect"] == "none"


def test_cooling_candidates_are_opt_in_and_receive_visible_freshness_decay():
    rows = [
        *_snapshot(AT - timedelta(hours=1), "x", "target", "old filler"),
        *_snapshot(AT, "x", "other", "current filler"),
    ]

    current_only = build_ranking_v2(rows, at=AT)
    include_cooling = build_ranking_v2(
        rows,
        at=AT,
        candidate_policy="include_cooling",
    )
    item = _event(include_cooling)

    assert all(row["event_key"] != "target" for row in current_only["ranking"])
    assert item["lifecycle"]["state"] == "cooling"
    assert item["score_components"]["freshness_multiplier"] == pytest.approx(
        0.5 ** (1 / 6), abs=1e-6
    )
    assert item["score"] == round(
        item["score_components"]["component_subtotal_points"]
        * item["score_components"]["freshness_multiplier"],
        2,
    )


def test_expired_state_is_available_for_history_without_entering_current_rank():
    lifecycle = classify_lifecycle_v2(
        current_at=AT,
        first_seen_at=AT - timedelta(days=10),
        last_seen_at=AT - timedelta(hours=13),
        previous_seen_at=AT - timedelta(hours=14),
        current_observed=False,
        momentum_delta=None,
        observed_hours=4,
    )

    assert lifecycle == {
        "state": "expired",
        "reason_code": "missing_beyond_cooling_window",
    }


def test_live_ranking_fails_closed_when_generated_or_demo_rows_are_mixed():
    mixed = [
        *_snapshot(AT, "x", "target", "filler"),
        _row(AT - timedelta(hours=1), "x", "generated", 1, provenance="generated"),
    ]

    with pytest.raises(ValueError, match="generated/demo/fixture"):
        build_ranking_v2(mixed, at=AT)
    with pytest.raises(ValueError, match="live_observed"):
        build_ranking_v2(_snapshot(AT, "x", "target"), at=AT, ranking_mode="demo")


def test_score_contract_is_explainable_and_component_sum_is_exact():
    rows = [
        *_snapshot(AT - timedelta(hours=1), "x", "target", "x old filler"),
        *_snapshot(AT - timedelta(hours=1), "google_trends", "target", "g old filler"),
        *_snapshot(AT, "x", "target", "x current filler"),
        *_snapshot(AT, "google_trends", "target", "g current filler"),
    ]

    result = build_ranking_v2(rows, at=AT)
    item = _event(result)
    components = item["score_components"]
    subtotal = round(
        sum(
            components[key]
            for key in (
                "current_points",
                "momentum_points",
                "persistence_points",
                "decayed_history_points",
                "cross_source_points",
            )
        ),
        2,
    )

    assert result["formula_version"] == components["formula_version"] == FORMULA_VERSION
    assert components["component_subtotal_points"] == subtotal
    assert components["freshness_multiplier"] == 1.0
    assert item["score"] == components["total_points"] == subtotal
    assert [part["max_points"] for part in item["score_explanation"]["components"]] == [
        40,
        20,
        20,
        15,
        5,
    ]
    assert result["data_readiness"]["status"] == "provisional_history"


def test_period_rankings_use_one_live_ledger_and_weekly_is_default():
    rows: list[dict] = []
    for age in range(48):
        stamp = AT - timedelta(hours=age)
        rows += _snapshot(stamp, "x", "target", f"x filler {age}")
        rows += _snapshot(stamp, "google_trends", "target", f"g filler {age}")

    result = build_period_rankings_v2(rows, at=AT)

    assert result["default_period"] == DEFAULT_RANKING_PERIOD == "weekly"
    assert [period["key"] for period in result["periods"]] == [
        "daily", "weekly", "monthly",
    ]
    assert [period["window"]["hours"] for period in result["periods"]] == [
        24, 168, 720,
    ]
    assert all(
        view["unified_ranking"][0]["event_key"] == "target"
        for view in result["views"].values()
    )
    assert result["views"]["daily"]["data_readiness"]["status"] == "ready"
    assert result["views"]["monthly"]["data_readiness"]["status"] == "provisional_history"
    assert all(
        view["parameters"]["candidate_policy"] == "current_only"
        and view["parameters"]["lifecycle_baseline_days"] == 60
        and view["parameters"]["ranking_mode"] == "live_observed"
        for view in result["views"].values()
    )


def test_period_windows_change_score_bearing_history_but_not_current_gate():
    rows = [
        *_snapshot(AT, "x", "target", "current filler"),
        *_snapshot(AT, "google_trends", "target", "current g filler"),
        *_snapshot(AT - timedelta(days=20), "x", "target", "old filler"),
        *_snapshot(AT - timedelta(days=20), "google_trends", "target", "old g filler"),
        *_snapshot(AT - timedelta(hours=1), "x", "expired", "hour filler"),
        *_snapshot(AT - timedelta(hours=1), "google_trends", "expired", "hour g filler"),
    ]

    result = build_period_rankings_v2(rows, at=AT)
    views = result["views"]

    assert all(
        "target" in {item["event_key"] for item in view["unified_ranking"]}
        and "expired" not in {item["event_key"] for item in view["unified_ranking"]}
        for view in views.values()
    )
    daily_target = next(
        item for item in views["daily"]["unified_ranking"]
        if item["event_key"] == "target"
    )
    assert daily_target["lifecycle"]["state"] == "rebounding"
    assert all(
        view["unified_ranking"][0]["lifecycle_baseline"]["ranking_effect"] == "none"
        for view in views.values()
    )


def test_period_rankings_reject_generated_rows_for_every_view():
    rows = [
        *_snapshot(AT, "x", "target"),
        _row(AT - timedelta(hours=1), "x", "demo", 1, provenance="generated"),
    ]

    with pytest.raises(ValueError, match="generated/demo/fixture"):
        build_period_rankings_v2(rows, at=AT)
