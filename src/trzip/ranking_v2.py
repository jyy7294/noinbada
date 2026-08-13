"""Source-fair, explainable ranking primitives for the TRZIP trend engine.

This module deliberately has no database, browser, ontology, or LLM dependency.
It expects the caller to pass quality-eligible X and Google observations and
returns JSON-serialisable dictionaries.  Keeping the score calculation pure
makes it possible to replay an observed ledger and a clearly-labelled demo
ledger with the same formula without mixing their provenance.

Input rows need ``observed_at``, ``source``, ``source_rank`` and the literal
``provenance='observed'``.  The event identity is read from ``event_key``, then
``canonical_topic``, then ``topic``.  The input must contain the complete
eligible source snapshots: snapshot sizes and source-specific eligible-hour
denominators are inferred from all rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence


FORMULA_VERSION = "current40_momentum20_persistence20_decay15_cross5_v2"
PERIOD_FORMULA_VERSION = "spread35_velocity25_breadth20_persistence10_recency10_v2"
DEFAULT_SOURCES = ("x", "google_trends")
DEFAULT_RANKING_PERIOD = "daily"
MINIMUM_COMPARISON_SNAPSHOTS = 3
RANKING_PERIODS = (
    {
        "key": "daily",
        "label": "24시간",
        "window_hours": 24,
    },
    {
        "key": "weekly",
        "label": "7일",
        "window_hours": 168,
    },
    {
        "key": "monthly",
        "label": "30일",
        "window_hours": 720,
    },
)
SOURCE_ALIASES = {
    "x": "x",
    "google": "google_trends",
    "google_trends": "google_trends",
}


def normalize_source_position(source_rank: int, snapshot_size: int) -> float:
    """Return a comparable 0..1 position inside one source snapshot.

    First place is always 1 and the last place is 0, regardless of whether the
    source currently exposes 30 or 200 rows.  A one-row snapshot is 1 because
    that row is both the first and only observed position.
    """

    if isinstance(source_rank, bool) or isinstance(snapshot_size, bool):
        raise ValueError("source_rank and snapshot_size must be positive integers")
    if not isinstance(source_rank, int) or not isinstance(snapshot_size, int):
        raise ValueError("source_rank and snapshot_size must be positive integers")
    if source_rank < 1 or snapshot_size < 1 or source_rank > snapshot_size:
        raise ValueError("source_rank must be within the source snapshot")
    if snapshot_size == 1:
        return 1.0
    return 1.0 - ((source_rank - 1) / (snapshot_size - 1))


def build_ranking_v2(
    observations: Iterable[Mapping[str, Any]],
    *,
    at: datetime,
    expected_sources: Sequence[str] = DEFAULT_SOURCES,
    candidate_policy: str = "current_only",
    cooling_hours: int = 12,
    cooling_half_life_hours: float = 6.0,
    persistence_window_hours: int = 168,
    persistence_maturity_hours: int = 96,
    history_window_hours: int = 168,
    history_half_life_hours: float = 24.0,
    lifecycle_baseline_days: int = 60,
    ranking_mode: str = "live_observed",
) -> dict[str, Any]:
    """Build a deterministic V2 ranking from quality-eligible observations.

    The score is exactly::

        40 current source-normalised position
      + 20 exact previous-hour momentum (10 neutral when unavailable)
      + 20 source-specific persistence with a 96-hour maturity ramp
      + 15 exponentially decayed observed history
      +  5 explicit current X+Google overlap

    ``candidate_policy='include_cooling'`` allows recently missing events to be
    returned for a cooling lane.  They receive no current/cross points and the
    component subtotal is multiplied by an explicit freshness decay.  The
    60-day lifecycle baseline never contributes points.

    Only ``ranking_mode='live_observed'`` is accepted.  Every row must carry
    ``provenance='observed'``; generated/demo/fixture rows fail closed instead
    of being silently mixed into a live score.
    """

    current_at = _floor_utc_hour(at)
    if cooling_hours < 0:
        raise ValueError("cooling_hours must be non-negative")
    if candidate_policy not in {"current_only", "include_cooling"}:
        raise ValueError("candidate_policy must be current_only or include_cooling")
    if ranking_mode != "live_observed":
        raise ValueError("ranking_v2 accepts live_observed rows only")
    if not isfinite(cooling_half_life_hours) or cooling_half_life_hours <= 0:
        raise ValueError("cooling_half_life_hours must be positive and finite")
    if persistence_window_hours < 1 or persistence_maturity_hours < 1:
        raise ValueError("persistence windows must be positive")
    if history_window_hours < 1:
        raise ValueError("history_window_hours must be positive")
    if not isfinite(history_half_life_hours) or history_half_life_hours <= 0:
        raise ValueError("history_half_life_hours must be positive and finite")
    if lifecycle_baseline_days < 1:
        raise ValueError("lifecycle_baseline_days must be positive")

    sources = _normalise_expected_sources(expected_sources)
    baseline_window_hours = lifecycle_baseline_days * 24
    lookback_hours = max(
        persistence_window_hours,
        history_window_hours,
        cooling_hours,
        baseline_window_hours,
    )
    earliest = current_at - timedelta(hours=lookback_hours)
    rows = _prepare_rows(observations, earliest=earliest, current_at=current_at, sources=sources)

    snapshot_sizes: dict[tuple[datetime, str], int] = {}
    source_hours: dict[str, set[datetime]] = {source: set() for source in sources}
    best_event_rank: dict[tuple[str, str, datetime], int] = {}
    event_last_seen: dict[str, datetime] = {}

    for row in rows:
        stamp = row["observed_at"]
        source = row["source"]
        rank = row["source_rank"]
        event_key = row["event_key"]
        snapshot_key = (stamp, source)
        snapshot_sizes[snapshot_key] = max(snapshot_sizes.get(snapshot_key, 0), rank)
        source_hours[source].add(stamp)
        event_source_hour = (event_key, source, stamp)
        best_event_rank[event_source_hour] = min(
            best_event_rank.get(event_source_hour, rank), rank
        )
        event_last_seen[event_key] = max(event_last_seen.get(event_key, stamp), stamp)

    current_available_sources = [
        source for source in sources if current_at in source_hours[source]
    ]
    previous_at = current_at - timedelta(hours=1)
    global_readiness = _global_readiness(
        sources=sources,
        source_hours=source_hours,
        current_at=current_at,
        persistence_maturity_hours=persistence_maturity_hours,
        persistence_window_hours=persistence_window_hours,
        history_window_hours=history_window_hours,
    )

    candidates: list[dict[str, Any]] = []
    for event_key, last_seen in sorted(event_last_seen.items()):
        current_sources = [
            source
            for source in sources
            if (event_key, source, current_at) in best_event_rank
        ]
        if candidate_policy == "current_only" and not current_sources:
            continue
        hours_since_last_seen = max(
            0.0, (current_at - last_seen).total_seconds() / 3600.0
        )
        if not current_sources and hours_since_last_seen > cooling_hours:
            continue

        scoring_sources = current_sources or [
            source
            for source in sources
            if (event_key, source, last_seen) in best_event_rank
        ]

        current_positions = {
            source: _event_position(
                event_key,
                source,
                current_at,
                best_event_rank=best_event_rank,
                snapshot_sizes=snapshot_sizes,
            )
            for source in current_sources
        }
        current_signal = _mean(current_positions.values()) if current_positions else 0.0

        comparable_momentum: dict[str, float] = {}
        momentum_unavailable_sources: list[str] = []
        for source in current_sources:
            # Never jump across a missing collection hour.  The exact previous
            # source snapshot must exist before momentum can be calculated.
            if previous_at not in source_hours[source]:
                momentum_unavailable_sources.append(source)
                continue
            current_position = current_positions[source]
            previous_position = _event_position(
                event_key,
                source,
                previous_at,
                best_event_rank=best_event_rank,
                snapshot_sizes=snapshot_sizes,
            )
            comparable_momentum[source] = current_position - previous_position

        if comparable_momentum:
            momentum_delta = max(-1.0, min(1.0, _mean(comparable_momentum.values())))
            momentum_signal = (momentum_delta + 1.0) / 2.0
            momentum_neutral_applied = False
        else:
            momentum_delta = None
            momentum_signal = 0.5
            momentum_neutral_applied = True

        per_source_persistence: dict[str, dict[str, Any]] = {}
        persistence_values: list[float] = []
        persistence_start = current_at - timedelta(hours=persistence_window_hours - 1)
        for source in scoring_sources:
            eligible = sorted(
                stamp
                for stamp in source_hours[source]
                if persistence_start <= stamp <= current_at
            )
            present = [
                stamp
                for stamp in eligible
                if (event_key, source, stamp) in best_event_rank
            ]
            presence_rate = len(present) / len(eligible) if eligible else 0.0
            maturity = min(len(eligible) / persistence_maturity_hours, 1.0)
            adjusted = presence_rate * maturity
            persistence_values.append(adjusted)
            per_source_persistence[source] = {
                "eligible_hours": len(eligible),
                "observed_hours": len(present),
                "presence_rate": round(presence_rate, 6),
                "maturity": round(maturity, 6),
                "adjusted_signal": round(adjusted, 6),
            }
        persistence_signal = _mean(persistence_values) if persistence_values else 0.0

        per_source_history: dict[str, dict[str, Any]] = {}
        decayed_history_values: list[float] = []
        history_start = current_at - timedelta(hours=history_window_hours)
        decay_capacity = sum(
            0.5 ** (age / history_half_life_hours)
            for age in range(1, history_window_hours + 1)
        )
        for source in scoring_sources:
            eligible_past = sorted(
                stamp
                for stamp in source_hours[source]
                if history_start <= stamp < current_at
            )
            weighted_evidence = 0.0
            eligible_weight = 0.0
            observed_past_hours = 0
            for stamp in eligible_past:
                age_hours = (current_at - stamp).total_seconds() / 3600.0
                weight = 0.5 ** (age_hours / history_half_life_hours)
                eligible_weight += weight
                position = _event_position(
                    event_key,
                    source,
                    stamp,
                    best_event_rank=best_event_rank,
                    snapshot_sizes=snapshot_sizes,
                )
                if position <= 0:
                    continue
                weighted_evidence += position * weight
                observed_past_hours += 1
            # ``weighted_presence`` is diagnostic source-coverage quality.
            # The score signal uses the fixed complete-window decay capacity:
            # a lone observation 48 hours ago must be weaker than a lone
            # observation one hour ago, and complete hourly history can reach 1.
            weighted_presence = (
                min(weighted_evidence / eligible_weight, 1.0)
                if eligible_weight
                else 0.0
            )
            history_maturity = min(len(eligible_past) / history_window_hours, 1.0)
            signal = min(weighted_evidence / decay_capacity, 1.0)
            decayed_history_values.append(signal)
            per_source_history[source] = {
                "eligible_past_hours": len(eligible_past),
                "observed_past_hours": observed_past_hours,
                "coverage": round(len(eligible_past) / history_window_hours, 6),
                "maturity": round(history_maturity, 6),
                "eligible_weight": round(eligible_weight, 6),
                "weighted_evidence": round(weighted_evidence, 6),
                "weighted_presence": round(weighted_presence, 6),
                "signal": round(signal, 6),
            }
        decayed_history_signal = (
            _mean(decayed_history_values) if decayed_history_values else 0.0
        )

        cross_source_signal = (
            1.0 if set(DEFAULT_SOURCES) <= set(current_sources) else 0.0
        )
        score_components = {
            "current_points": round(40.0 * current_signal, 2),
            "momentum_points": round(20.0 * momentum_signal, 2),
            "persistence_points": round(20.0 * persistence_signal, 2),
            "decayed_history_points": round(15.0 * decayed_history_signal, 2),
            "cross_source_points": round(5.0 * cross_source_signal, 2),
            "formula_version": FORMULA_VERSION,
            "rounding_policy": "each_component_2dp_then_sum_2dp",
        }
        component_subtotal = round(
            sum(
                score_components[key]
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
        freshness_multiplier = (
            1.0
            if current_sources
            else 0.5 ** (hours_since_last_seen / cooling_half_life_hours)
        )
        total = round(component_subtotal * freshness_multiplier, 2)
        score_components["component_subtotal_points"] = component_subtotal
        score_components["freshness_multiplier"] = round(freshness_multiplier, 6)
        score_components["total_points"] = total

        event_stamps = sorted(
            {
                stamp
                for (key, _source, stamp) in best_event_rank
                if key == event_key
                and current_at - timedelta(hours=baseline_window_hours) <= stamp <= current_at
            }
        )
        previous_seen_at = next(
            (stamp for stamp in reversed(event_stamps) if stamp < current_at),
            None,
        )
        lifecycle = classify_lifecycle_v2(
            current_at=current_at,
            first_seen_at=event_stamps[0],
            last_seen_at=last_seen,
            previous_seen_at=previous_seen_at,
            current_observed=bool(current_sources),
            momentum_delta=momentum_delta,
            observed_hours=len(event_stamps),
            cooling_hours=cooling_hours,
        )
        baseline_dates = {stamp.date().isoformat() for stamp in event_stamps}
        lifecycle_baseline = {
            "window_days": lifecycle_baseline_days,
            "first_seen_at": event_stamps[0].isoformat(),
            "last_seen_at": event_stamps[-1].isoformat(),
            "observed_hours": len(event_stamps),
            "observed_days": len(baseline_dates),
            "seen_before_current_hour": previous_seen_at is not None,
            "previous_seen_at": (
                previous_seen_at.isoformat() if previous_seen_at is not None else None
            ),
            "ranking_effect": "none",
            "purpose": "lifecycle_classification_only",
        }

        event_readiness = _event_readiness(
            sources=sources,
            current_sources=current_sources,
            comparable_momentum=comparable_momentum,
            momentum_unavailable_sources=momentum_unavailable_sources,
            per_source_persistence=per_source_persistence,
            per_source_history=per_source_history,
            persistence_maturity_hours=persistence_maturity_hours,
        )
        score_explanation = {
            "formula": (
                "40 current + 20 exact-hour momentum + 20 per-source persistence "
                "+ 15 exponentially decayed history + 5 explicit cross-source"
            ),
            "components": [
                {
                    "key": "current",
                    "points": score_components["current_points"],
                    "max_points": 40,
                    "basis": "mean source-normalised current position over observed current sources",
                },
                {
                    "key": "momentum",
                    "points": score_components["momentum_points"],
                    "max_points": 20,
                    "basis": (
                        "exact previous-hour position change; neutral 10 points when no exact comparison exists"
                    ),
                },
                {
                    "key": "persistence",
                    "points": score_components["persistence_points"],
                    "max_points": 20,
                    "basis": (
                        "mean source-specific presence rate multiplied by source-specific history maturity"
                    ),
                },
                {
                    "key": "decayed_history",
                    "points": score_components["decayed_history_points"],
                    "max_points": 15,
                    "basis": (
                        f"observed history with {history_half_life_hours:g}h exponential half-life"
                    ),
                },
                {
                    "key": "cross_source",
                    "points": score_components["cross_source_points"],
                    "max_points": 5,
                    "basis": "5 points only when the event is currently observed by both X and Google",
                },
            ],
            "freshness": {
                "multiplier": round(freshness_multiplier, 6),
                "basis": (
                    "1 while currently observed; otherwise exponential cooling decay "
                    f"with {cooling_half_life_hours:g}h half-life"
                ),
            },
            "lifecycle_baseline_ranking_effect": "none",
        }

        candidates.append(
            {
                "event_key": event_key,
                "score": total,
                "current_sources": current_sources,
                "missing_current_sources": [
                    source for source in sources if source not in current_sources
                ],
                "last_seen_at": last_seen.isoformat(),
                "hours_since_last_seen": round(hours_since_last_seen, 3),
                "is_current": bool(current_sources),
                "candidate_policy": candidate_policy,
                "lifecycle": lifecycle,
                "lifecycle_baseline": lifecycle_baseline,
                "signals": {
                    "current": round(current_signal, 6),
                    "momentum": round(momentum_signal, 6),
                    "momentum_delta": (
                        round(momentum_delta, 6) if momentum_delta is not None else None
                    ),
                    "persistence": round(persistence_signal, 6),
                    "decayed_history": round(decayed_history_signal, 6),
                    "cross_source": cross_source_signal,
                },
                "source_metrics": {
                    "current_positions": {
                        key: round(value, 6) for key, value in current_positions.items()
                    },
                    "momentum_deltas": {
                        key: round(value, 6) for key, value in comparable_momentum.items()
                    },
                    "persistence": per_source_persistence,
                    "decayed_history": per_source_history,
                },
                "score_components": score_components,
                "score_explanation": score_explanation,
                "data_readiness": event_readiness,
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["signals"]["current"],
            item["event_key"],
        )
    )
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank

    return {
        "formula_version": FORMULA_VERSION,
        "generated_at": current_at.isoformat(),
        "expected_sources": list(sources),
        "ranking": candidates,
        "data_readiness": global_readiness,
        "parameters": {
            "candidate_policy": candidate_policy,
            "cooling_hours": cooling_hours,
            "cooling_half_life_hours": cooling_half_life_hours,
            "persistence_window_hours": persistence_window_hours,
            "persistence_maturity_hours": persistence_maturity_hours,
            "history_window_hours": history_window_hours,
            "history_half_life_hours": history_half_life_hours,
            "lifecycle_baseline_days": lifecycle_baseline_days,
            "ranking_mode": ranking_mode,
        },
    }


def build_period_rankings_v2(
    observations: Iterable[Mapping[str, Any]],
    *,
    at: datetime,
    expected_sources: Sequence[str] = DEFAULT_SOURCES,
) -> dict[str, Any]:
    """Build 24-hour, 7-day and 30-day observed-period ranking views.

    Every view reads the same materialised quality-eligible live ledger and
    aggregates every event observed inside its own period. The 60-day baseline
    remains lifecycle-only. ``daily`` is the product/default period used by
    top-level output.
    """

    rows = [dict(row) for row in observations]
    current_at = _floor_utc_hour(at)
    views: dict[str, dict[str, Any]] = {}
    periods: list[dict[str, Any]] = []
    for definition in RANKING_PERIODS:
        period_key = str(definition["key"])
        window_hours = int(definition["window_hours"])
        result = build_period_ranking_v2(
            rows,
            at=current_at,
            window_hours=window_hours,
            expected_sources=expected_sources,
            lifecycle_baseline_days=60,
            ranking_mode="live_observed",
        )
        window = {
            "from": (current_at - timedelta(hours=window_hours - 1)).isoformat(),
            "to": current_at.isoformat(),
            "hours": window_hours,
            "score_history_hours": window_hours,
            "lifecycle_baseline_days": 60,
        }
        period = {
            "key": period_key,
            "label": str(definition["label"]),
            "default": period_key == DEFAULT_RANKING_PERIOD,
            "window": window,
        }
        periods.append(period)
        views[period_key] = {
            **period,
            "formula_version": result["formula_version"],
            "data_readiness": result["data_readiness"],
            "parameters": result["parameters"],
            "unified_ranking": result["ranking"],
        }
    return {
        "default_period": DEFAULT_RANKING_PERIOD,
        "periods": periods,
        "views": views,
    }


def build_period_ranking_v2(
    observations: Iterable[Mapping[str, Any]],
    *,
    at: datetime,
    window_hours: int,
    expected_sources: Sequence[str] = DEFAULT_SOURCES,
    lifecycle_baseline_days: int = 60,
    ranking_mode: str = "live_observed",
) -> dict[str, Any]:
    """Aggregate every live-observed event in one ranking period.

    Formula: 35 attention strength + 25 measured velocity + 20 source breadth
    + 10 persistence + 10 last-seen recency. Attention strength is the mean
    of each observed source's 70% recency-weighted average position and 30%
    peak position. Momentum uses the previous equal-length window when source
    coverage exists, then falls back to first-half versus second-half. Every
    compared source requires three snapshots in both sides; otherwise velocity
    is unavailable and contributes zero points.
    """

    current_at = _floor_utc_hour(at)
    if window_hours < 2:
        raise ValueError("window_hours must be at least two")
    if ranking_mode != "live_observed":
        raise ValueError("period ranking accepts live_observed rows only")
    if lifecycle_baseline_days < 1:
        raise ValueError("lifecycle_baseline_days must be positive")
    sources = _normalise_expected_sources(expected_sources)
    baseline_hours = lifecycle_baseline_days * 24
    rows = _prepare_rows(
        observations,
        earliest=current_at - timedelta(hours=baseline_hours),
        current_at=current_at,
        sources=sources,
    )
    snapshot_sizes: dict[tuple[datetime, str], int] = {}
    source_hours: dict[str, set[datetime]] = {source: set() for source in sources}
    event_ranks: dict[tuple[str, str, datetime], int] = {}
    event_hours: dict[str, set[datetime]] = defaultdict(set)
    for row in rows:
        stamp, source, event_key, rank = (
            row["observed_at"], row["source"], row["event_key"], row["source_rank"]
        )
        snapshot_sizes[(stamp, source)] = max(
            snapshot_sizes.get((stamp, source), 0), rank
        )
        source_hours[source].add(stamp)
        key = (event_key, source, stamp)
        event_ranks[key] = min(event_ranks.get(key, rank), rank)
        event_hours[event_key].add(stamp)

    period_start = current_at - timedelta(hours=window_hours - 1)
    previous_end = period_start - timedelta(hours=1)
    previous_start = previous_end - timedelta(hours=window_hours - 1)
    half_boundary = period_start + timedelta(hours=window_hours // 2)
    current_eligible = {
        source: sorted(
            stamp for stamp in source_hours[source]
            if period_start <= stamp <= current_at
        )
        for source in sources
    }
    previous_eligible = {
        source: sorted(
            stamp for stamp in source_hours[source]
            if previous_start <= stamp <= previous_end
        )
        for source in sources
    }

    def source_strength(event_key: str, source: str, stamps: Sequence[datetime], end: datetime) -> float:
        observed: list[tuple[float, float]] = []
        half_life = max(window_hours / 2.0, 1.0)
        for stamp in stamps:
            position = _event_position(
                event_key, source, stamp,
                best_event_rank=event_ranks,
                snapshot_sizes=snapshot_sizes,
            )
            if (event_key, source, stamp) not in event_ranks:
                continue
            age = max(0.0, (end - stamp).total_seconds() / 3600.0)
            observed.append((position, 0.5 ** (age / half_life)))
        if not observed:
            return 0.0
        weighted_mean = sum(value * weight for value, weight in observed) / sum(
            weight for _value, weight in observed
        )
        peak = max(value for value, _weight in observed)
        return 0.7 * weighted_mean + 0.3 * peak

    candidates: list[dict[str, Any]] = []
    for event_key, all_stamps in sorted(event_hours.items()):
        period_stamps = sorted(
            stamp for stamp in all_stamps if period_start <= stamp <= current_at
        )
        if not period_stamps:
            continue
        observed_sources = [
            source for source in sources
            if any((event_key, source, stamp) in event_ranks for stamp in period_stamps)
        ]
        strengths = {
            source: source_strength(
                event_key, source, current_eligible[source], current_at
            )
            for source in observed_sources
        }
        # X and Google always own equal shares of the attention component.
        # A single-source term therefore cannot inherit the missing source's
        # attention weight (source breadth is rewarded separately below).
        period_strength = _mean(strengths.get(source, 0.0) for source in sources)

        momentum_deltas: dict[str, float] = {}
        momentum_basis: dict[str, str] = {}
        momentum_event_observations: dict[str, dict[str, int]] = {}
        for source in observed_sources:
            current_strength = strengths[source]
            current_event_count = sum(
                (event_key, source, stamp) in event_ranks
                for stamp in current_eligible[source]
            )
            previous_event_count = sum(
                (event_key, source, stamp) in event_ranks
                for stamp in previous_eligible[source]
            )
            if (
                len(current_eligible[source]) >= MINIMUM_COMPARISON_SNAPSHOTS
                and len(previous_eligible[source]) >= MINIMUM_COMPARISON_SNAPSHOTS
                and current_event_count >= MINIMUM_COMPARISON_SNAPSHOTS
            ):
                previous_strength = source_strength(
                    event_key, source, previous_eligible[source], previous_end
                )
                momentum_deltas[source] = current_strength - previous_strength
                momentum_basis[source] = "previous_equal_period"
                momentum_event_observations[source] = {
                    "current": current_event_count,
                    "comparison": previous_event_count,
                }
                continue
            first_half = [
                stamp for stamp in current_eligible[source]
                if period_start <= stamp < half_boundary
            ]
            second_half = [
                stamp for stamp in current_eligible[source]
                if half_boundary <= stamp <= current_at
            ]
            first_half_event_count = sum(
                (event_key, source, stamp) in event_ranks
                for stamp in first_half
            )
            second_half_event_count = sum(
                (event_key, source, stamp) in event_ranks
                for stamp in second_half
            )
            if (
                len(first_half) >= MINIMUM_COMPARISON_SNAPSHOTS
                and len(second_half) >= MINIMUM_COMPARISON_SNAPSHOTS
                and second_half_event_count >= MINIMUM_COMPARISON_SNAPSHOTS
            ):
                momentum_deltas[source] = source_strength(
                    event_key, source, second_half, current_at
                ) - source_strength(
                    event_key, source, first_half, half_boundary - timedelta(hours=1)
                )
                momentum_basis[source] = "current_period_half_change"
                momentum_event_observations[source] = {
                    "current": second_half_event_count,
                    "comparison": first_half_event_count,
                }
        if momentum_deltas:
            momentum_delta = max(-1.0, min(1.0, _mean(momentum_deltas.values())))
            # Velocity is an acceleration signal, not a symmetric direction
            # score. Falling or flat terms receive no velocity points.
            momentum_signal = max(0.0, momentum_delta)
            momentum_status = "measured"
        else:
            momentum_delta = None
            momentum_signal = 0.0
            momentum_status = "unavailable"

        persistence_by_source: dict[str, dict[str, Any]] = {}
        persistence_signals: list[float] = []
        for source in sources:
            eligible = current_eligible[source]
            present = [
                stamp for stamp in eligible
                if (event_key, source, stamp) in event_ranks
            ]
            # A feed with only two captured hours must not look as persistent
            # as a mature 24-hour feed. Missing source snapshots count as
            # unobserved against the selected product window.
            signal = len(present) / window_hours
            persistence_signals.append(signal)
            persistence_by_source[source] = {
                "eligible_hours": len(eligible),
                "observed_hours": len(present),
                "presence_rate": round(signal, 6),
                "window_hours": window_hours,
            }
        persistence = _mean(persistence_signals)
        last_seen = max(period_stamps)
        hours_since_last_seen = max(
            0.0, (current_at - last_seen).total_seconds() / 3600.0
        )
        recency_half_life = window_hours / 2.0
        recency = 0.5 ** (hours_since_last_seen / recency_half_life)
        cross = float(set(sources).issubset(observed_sources))
        components = {
            "period_strength_points": round(35 * period_strength, 2),
            "momentum_points": round(25 * momentum_signal, 2),
            "persistence_points": round(10 * persistence, 2),
            "recency_points": round(10 * recency, 2),
            "cross_source_points": round(20 * cross, 2),
            "formula_version": PERIOD_FORMULA_VERSION,
            "rounding_policy": "each_component_2dp_then_sum_2dp",
        }
        total = round(sum(
            components[key] for key in (
                "period_strength_points", "momentum_points", "persistence_points",
                "recency_points", "cross_source_points",
            )
        ), 2)
        components["total_points"] = total

        baseline_stamps = sorted(
            stamp for stamp in all_stamps
            if current_at - timedelta(hours=baseline_hours) <= stamp <= current_at
        )
        previous_seen = next(
            (stamp for stamp in reversed(baseline_stamps) if stamp < last_seen), None
        )
        lifecycle = classify_lifecycle_v2(
            current_at=current_at,
            first_seen_at=baseline_stamps[0],
            last_seen_at=last_seen,
            previous_seen_at=previous_seen,
            current_observed=last_seen == current_at,
            momentum_delta=momentum_delta,
            observed_hours=len(baseline_stamps),
        )
        coverage_by_source = {
            source: round(len(current_eligible[source]) / window_hours, 6)
            for source in sources
        }
        current_sources = [
            source for source in observed_sources
            if (event_key, source, current_at) in event_ranks
        ]
        candidates.append({
            "event_key": event_key,
            "score": total,
            "score_components": components,
            "candidate_status": "is_current" if current_sources else "period_observed",
            "is_current": bool(current_sources),
            "current_sources": current_sources,
            "period_sources": observed_sources,
            "last_seen_at": last_seen.isoformat(),
            "hours_since_last_seen": round(hours_since_last_seen, 3),
            "freshness": {
                "signal": round(recency, 6),
                "half_life_hours": recency_half_life,
                "hours_since_last_seen": round(hours_since_last_seen, 3),
            },
            "signals": {
                "period_strength": round(period_strength, 6),
                "momentum": round(momentum_signal, 6),
                "momentum_delta": round(momentum_delta, 6) if momentum_delta is not None else None,
                "persistence": round(persistence, 6),
                "recency": round(recency, 6),
                "cross_source": cross,
            },
            "source_metrics": {
                "period_strength": {key: round(value, 6) for key, value in strengths.items()},
                "momentum_deltas": {key: round(value, 6) for key, value in momentum_deltas.items()},
                "momentum_basis": momentum_basis,
                "momentum_event_observations": momentum_event_observations,
                "persistence": persistence_by_source,
            },
            "data_readiness": {
                "status": "ready" if all(value >= 0.8 for value in coverage_by_source.values()) else "provisional",
                "coverage_by_source": coverage_by_source,
                "momentum_status": momentum_status,
                "minimum_event_observations_for_momentum": MINIMUM_COMPARISON_SNAPSHOTS,
            },
            "lifecycle": lifecycle,
            "lifecycle_baseline": {
                "window_days": lifecycle_baseline_days,
                "first_seen_at": baseline_stamps[0].isoformat(),
                "last_seen_at": baseline_stamps[-1].isoformat(),
                "observed_hours": len(baseline_stamps),
                "ranking_effect": "none",
                "purpose": "lifecycle_classification_only",
            },
            "score_explanation": {
                "formula": (
                    "35 attention strength + 25 measured velocity + "
                    "20 X-Google breadth + 10 persistence + 10 recency"
                ),
                "momentum_status": momentum_status,
                "momentum_basis": momentum_basis,
                "lifecycle_baseline_ranking_effect": "none",
            },
        })
    # Build a directly comparable previous-period table.  Its momentum uses
    # the same documented half-period fallback because the immediately prior
    # equal window is itself the comparison target.  This table never adds a
    # stale event to the current period; it exists only to expose honest rank
    # change instead of comparing against the previous collection hour.
    previous_scores: list[tuple[str, float]] = []
    previous_coverage_available = any(previous_eligible.values())
    previous_half_boundary = previous_start + timedelta(hours=window_hours // 2)
    previous_events = {
        event_key
        for event_key, stamps in event_hours.items()
        if any(previous_start <= stamp <= previous_end for stamp in stamps)
    }
    for event_key in sorted(previous_events):
        observed_sources = [
            source
            for source in sources
            if any(
                (event_key, source, stamp) in event_ranks
                for stamp in previous_eligible[source]
            )
        ]
        strengths = {
            source: source_strength(
                event_key, source, previous_eligible[source], previous_end
            )
            for source in observed_sources
        }
        strength_signal = _mean(strengths.get(source, 0.0) for source in sources)
        persistence_values: list[float] = []
        half_deltas: list[float] = []
        for source in sources:
            eligible = previous_eligible[source]
            present = [
                stamp
                for stamp in eligible
                if (event_key, source, stamp) in event_ranks
            ]
            persistence_values.append(len(present) / window_hours)
            first_half = [
                stamp for stamp in eligible
                if previous_start <= stamp < previous_half_boundary
            ]
            second_half = [
                stamp for stamp in eligible
                if previous_half_boundary <= stamp <= previous_end
            ]
            if (
                len(first_half) >= MINIMUM_COMPARISON_SNAPSHOTS
                and len(second_half) >= MINIMUM_COMPARISON_SNAPSHOTS
            ):
                half_deltas.append(
                    source_strength(event_key, source, second_half, previous_end)
                    - source_strength(
                        event_key,
                        source,
                        first_half,
                        previous_half_boundary - timedelta(hours=1),
                    )
                )
        if half_deltas:
            previous_delta = max(-1.0, min(1.0, _mean(half_deltas)))
            previous_momentum = max(0.0, previous_delta)
        else:
            previous_momentum = 0.0
        previous_last_seen = max(
            stamp
            for stamp in event_hours[event_key]
            if previous_start <= stamp <= previous_end
        )
        previous_age = max(
            0.0, (previous_end - previous_last_seen).total_seconds() / 3600.0
        )
        previous_recency = 0.5 ** (previous_age / (window_hours / 2.0))
        previous_cross = len(set(observed_sources) & set(sources)) / len(sources)
        previous_score = round(
            35 * strength_signal
            + 25 * previous_momentum
            + 10 * _mean(persistence_values)
            + 10 * previous_recency
            + 20 * previous_cross,
            2,
        )
        previous_scores.append((event_key, previous_score))
    previous_scores.sort(key=lambda item: (-item[1], item[0]))
    previous_rank_by_event = {
        event_key: rank
        for rank, (event_key, _score) in enumerate(previous_scores, 1)
    }

    candidates.sort(key=lambda item: (-item["score"], item["event_key"]))
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank
        previous_rank = previous_rank_by_event.get(item["event_key"])
        item["previous_period_rank"] = previous_rank
        item["rank_change"] = (
            previous_rank - rank if previous_rank is not None else None
        )
        item["rank_change_status"] = (
            "measured"
            if previous_rank is not None
            else "new_in_period"
            if previous_coverage_available
            else "unavailable_no_previous_period_coverage"
        )
    return {
        "formula_version": PERIOD_FORMULA_VERSION,
        "generated_at": current_at.isoformat(),
        "expected_sources": list(sources),
        "ranking": candidates,
        "data_readiness": {
            "status": "ready" if all(
                len(current_eligible[source]) / window_hours >= 0.8 for source in sources
            ) else "provisional",
            "coverage_by_source": {
                source: round(len(current_eligible[source]) / window_hours, 6)
                for source in sources
            },
            "previous_period_coverage_available": previous_coverage_available,
        },
        "parameters": {
            "candidate_policy": "period_observed",
            "window_hours": window_hours,
            "recency_half_life_hours": window_hours / 2.0,
            "lifecycle_baseline_days": lifecycle_baseline_days,
            "ranking_mode": ranking_mode,
        },
    }


def classify_lifecycle_v2(
    *,
    current_at: datetime,
    first_seen_at: datetime,
    last_seen_at: datetime,
    previous_seen_at: datetime | None,
    current_observed: bool,
    momentum_delta: float | None,
    observed_hours: int,
    cooling_hours: int = 12,
    new_hours: int = 3,
    rebound_gap_hours: int = 24,
) -> dict[str, str]:
    """Classify lifecycle without changing rank points.

    The caller may provide observations from a 60-day baseline.  That baseline
    only distinguishes a genuinely new event from a returning event; it is not
    a score bonus.
    """

    now = _floor_utc_hour(current_at)
    first_seen = _parse_hour(first_seen_at, field="first_seen_at")
    last_seen = _parse_hour(last_seen_at, field="last_seen_at")
    previous_seen = (
        _parse_hour(previous_seen_at, field="previous_seen_at")
        if previous_seen_at is not None
        else None
    )
    if first_seen > last_seen or last_seen > now:
        raise ValueError("lifecycle timestamps must satisfy first <= last <= current")
    if observed_hours < 1:
        raise ValueError("observed_hours must be positive")

    age_since_last = (now - last_seen).total_seconds() / 3600.0
    if not current_observed:
        if age_since_last <= cooling_hours:
            return {"state": "cooling", "reason_code": "recently_missing_within_cooling_window"}
        return {"state": "expired", "reason_code": "missing_beyond_cooling_window"}

    if previous_seen is not None:
        gap = (now - previous_seen).total_seconds() / 3600.0
        if gap >= rebound_gap_hours:
            return {"state": "rebounding", "reason_code": "returned_after_long_observation_gap"}
    age_since_first = (now - first_seen).total_seconds() / 3600.0
    if age_since_first < new_hours and observed_hours <= new_hours:
        return {"state": "new", "reason_code": "first_observed_within_new_window"}
    if momentum_delta is None:
        return {
            "state": "insufficient_data",
            "reason_code": "comparison_window_not_ready",
        }
    if momentum_delta is not None and momentum_delta >= 0.12:
        return {"state": "rising", "reason_code": "normalised_position_rising"}
    if observed_hours >= new_hours:
        return {"state": "sustained", "reason_code": "repeated_observation"}
    return {"state": "new", "reason_code": "insufficient_history_for_sustained"}


def _prepare_rows(
    observations: Iterable[Mapping[str, Any]],
    *,
    earliest: datetime,
    current_at: datetime,
    sources: tuple[str, ...],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, row in enumerate(observations):
        provenance = str(row.get("provenance") or "").strip().lower()
        if provenance != "observed":
            raise ValueError(
                f"observation {index} must have provenance='observed'; "
                "generated/demo/fixture rows cannot enter the live ranking"
            )
        if row.get("quality_status") not in (None, "eligible"):
            continue
        source = SOURCE_ALIASES.get(str(row.get("source", "")).strip().lower())
        if source not in sources:
            continue
        event_key = str(
            row.get("event_key")
            or row.get("canonical_topic")
            or row.get("topic")
            or ""
        ).strip()
        if not event_key:
            raise ValueError(f"observation {index} has no event identity")
        stamp = _parse_hour(row.get("observed_at"), field=f"observation {index}.observed_at")
        if stamp < earliest or stamp > current_at:
            continue
        rank_value = row.get("source_rank")
        if isinstance(rank_value, bool):
            raise ValueError(f"observation {index}.source_rank must be a positive integer")
        try:
            rank = int(rank_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"observation {index}.source_rank must be a positive integer"
            ) from exc
        if rank < 1 or rank != rank_value:
            raise ValueError(f"observation {index}.source_rank must be a positive integer")
        prepared.append(
            {
                "event_key": event_key,
                "observed_at": stamp,
                "source": source,
                "source_rank": rank,
            }
        )
    return prepared


def _event_position(
    event_key: str,
    source: str,
    stamp: datetime,
    *,
    best_event_rank: Mapping[tuple[str, str, datetime], int],
    snapshot_sizes: Mapping[tuple[datetime, str], int],
) -> float:
    rank = best_event_rank.get((event_key, source, stamp))
    if rank is None:
        return 0.0
    return normalize_source_position(rank, snapshot_sizes[(stamp, source)])


def _global_readiness(
    *,
    sources: tuple[str, ...],
    source_hours: Mapping[str, set[datetime]],
    current_at: datetime,
    persistence_maturity_hours: int,
    persistence_window_hours: int,
    history_window_hours: int,
) -> dict[str, Any]:
    by_source: dict[str, dict[str, Any]] = {}
    for source in sources:
        all_hours = sorted(source_hours[source])
        persistence_start = current_at - timedelta(hours=persistence_window_hours - 1)
        history_start = current_at - timedelta(hours=history_window_hours)
        persistence_hours = [
            stamp for stamp in all_hours if persistence_start <= stamp <= current_at
        ]
        history_hours = [
            stamp for stamp in all_hours if history_start <= stamp < current_at
        ]
        eligible_count = len(persistence_hours)
        by_source[source] = {
            "current_snapshot_available": current_at in source_hours[source],
            "exact_previous_snapshot_available": (
                current_at - timedelta(hours=1) in source_hours[source]
            ),
            "eligible_hours": eligible_count,
            "persistence_maturity": round(
                min(eligible_count / persistence_maturity_hours, 1.0), 6
            ),
            "history_eligible_hours": len(history_hours),
            "history_coverage": round(
                min(len(history_hours) / history_window_hours, 1.0), 6
            ),
            "first_eligible_at": all_hours[0].isoformat() if all_hours else None,
            "last_eligible_at": all_hours[-1].isoformat() if all_hours else None,
        }
    current_count = sum(
        1 for source in sources if by_source[source]["current_snapshot_available"]
    )
    mature = all(
        by_source[source]["eligible_hours"] >= persistence_maturity_hours
        for source in sources
    )
    if current_count == 0:
        status = "unavailable"
    elif current_count < len(sources):
        status = "provisional_single_source"
    elif mature:
        status = "ready"
    else:
        status = "provisional_history"
    return {
        "status": status,
        "is_ready": status == "ready",
        "by_source": by_source,
    }


def _event_readiness(
    *,
    sources: tuple[str, ...],
    current_sources: list[str],
    comparable_momentum: Mapping[str, float],
    momentum_unavailable_sources: list[str],
    per_source_persistence: Mapping[str, Mapping[str, Any]],
    per_source_history: Mapping[str, Mapping[str, Any]],
    persistence_maturity_hours: int,
) -> dict[str, Any]:
    if not comparable_momentum:
        momentum_status = "unavailable_neutral"
    elif len(comparable_momentum) < len(current_sources):
        momentum_status = "partial"
    else:
        momentum_status = "ready"
    persistence_ready = bool(per_source_persistence) and all(
        values["eligible_hours"] >= persistence_maturity_hours
        for values in per_source_persistence.values()
    )
    history_ready = bool(per_source_history) and all(
        values["coverage"] >= 0.8 for values in per_source_history.values()
    )
    fully_current = set(current_sources) == set(sources)
    status = (
        "ready"
        if fully_current and momentum_status == "ready" and persistence_ready and history_ready
        else "provisional"
    )
    warnings: list[str] = []
    if not fully_current:
        warnings.append("single_source_current_observation")
    if momentum_status == "unavailable_neutral":
        warnings.append("momentum_neutral_due_to_missing_exact_previous_snapshot")
    elif momentum_status == "partial":
        warnings.append("momentum_uses_partial_source_history")
    if not persistence_ready:
        warnings.append("persistence_history_not_mature")
    if not history_ready:
        warnings.append("decayed_history_coverage_low")
    return {
        "status": status,
        "is_ready": status == "ready",
        "momentum": {
            "status": momentum_status,
            "neutral_applied": not comparable_momentum,
            "comparable_sources": sorted(comparable_momentum),
            "unavailable_sources": sorted(momentum_unavailable_sources),
        },
        "persistence": {
            "status": "ready" if persistence_ready else "provisional",
            "maturity_required_hours": persistence_maturity_hours,
        },
        "decayed_history": {
            "status": "ready" if history_ready else "provisional",
        },
        "warnings": warnings,
    }


def _normalise_expected_sources(expected_sources: Sequence[str]) -> tuple[str, ...]:
    normalised: list[str] = []
    for value in expected_sources:
        source = SOURCE_ALIASES.get(str(value).strip().lower())
        if source is None:
            raise ValueError(f"unsupported ranking source: {value!r}")
        if source not in normalised:
            normalised.append(source)
    if not normalised:
        raise ValueError("expected_sources must contain X or Google")
    return tuple(normalised)


def _floor_utc_hour(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("at must be a timezone-aware datetime")
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _parse_hour(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    else:
        raise ValueError(f"{field} must be an ISO datetime")
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    parsed = parsed.astimezone(UTC)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError(f"{field} must be aligned to an exact hour")
    return parsed


def _mean(values: Iterable[float]) -> float:
    materialised = list(values)
    return sum(materialised) / len(materialised) if materialised else 0.0
