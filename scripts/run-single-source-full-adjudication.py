"""Produce a final, exhaustive 48-hour source-only trend adjudication."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trzip.event_resolution import normalize_event_key
from trzip.source_adjudication import POLICY_VERSION, adjudicate_source_expression


ALLOWED_CATEGORIES = {
    "food", "content", "sports", "lifestyle",
    "culture", "consumer", "technology", "market",
}


def parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--observed-at must include a timezone")
    return parsed.astimezone(UTC)


def _write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _load_review_overlay(path: Path | None, source: str) -> tuple[dict[str, dict], dict]:
    if path is None:
        return {}, {
            "review_batch_id": None,
            "reviewed_first_pass_not_selected": 0,
            "configured_terms": 0,
        }
    overlay = json.loads(path.read_text(encoding="utf-8"))
    if overlay.get("policy", {}).get("rank_effect") != "none":
        raise ValueError("review overlay must have rank_effect=none")
    if overlay.get("policy", {}).get("manual_whitelist_for_future_rank") is not False:
        raise ValueError("review overlay cannot be a future ranking whitelist")

    decisions: dict[str, dict] = {}
    for group in overlay.get("include_groups", []):
        if group.get("source") != source:
            continue
        category = group.get("category")
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"invalid review category: {category}")
        canonical_name = " ".join(str(group.get("canonical_name") or "").split())
        if not canonical_name:
            raise ValueError("review include group must have canonical_name")
        for term in group.get("terms", []):
            key = normalize_event_key(str(term))
            if key in decisions:
                raise ValueError(f"duplicate review decision for {source}:{term}")
            decisions[key] = {
                "decision": "included",
                "reason_code": "included_after_exhaustive_context_review",
                "reason": group.get("reason"),
                "broad_category": category,
                "canonical_name": canonical_name,
                "review_origin": "explicit_context_review",
            }

    for item in overlay.get("exclude_terms", []):
        if item.get("source") != source:
            continue
        key = normalize_event_key(str(item.get("term") or ""))
        if key in decisions:
            raise ValueError(f"conflicting review decision for {source}:{item.get('term')}")
        decisions[key] = {
            "decision": "excluded",
            "reason_code": item.get("reason_code") or "excluded_after_exhaustive_context_review",
            "reason": item.get("reason"),
            "broad_category": None,
            "canonical_name": None,
            "review_origin": "explicit_context_review",
        }

    return decisions, {
        "review_batch_id": overlay.get("review_batch_id"),
        "reviewed_first_pass_not_selected": overlay.get("scope", {}).get("reviewed_first_pass_not_selected", 0),
        "configured_terms": len(decisions),
    }


def _final_exclusion(first_pass: dict) -> dict:
    mapping = {
        "generic_expression_without_event_context": "excluded_generic_expression_without_trigger",
        "hashtag_campaign_without_concrete_event_context": "excluded_coordinated_hashtag_without_independent_trigger",
        "standalone_person_or_entity_name_without_event_context": "excluded_standalone_name_without_trigger",
        "sports_subject_without_specific_fixture_or_outcome": "excluded_sports_subject_without_fixture_or_outcome",
        "named_expression_without_category_or_event_context": "excluded_named_expression_without_verified_trigger",
        "context_insufficient_from_source_label": "excluded_no_concrete_trigger_in_observed_expression",
        "empty_expression": "excluded_empty_expression",
    }
    code = mapping.get(
        str(first_pass.get("reason_code")),
        "excluded_after_full_expression_review",
    )
    return {
        **first_pass,
        "decision": "excluded",
        "reason_code": code,
        "reason": "원천 표현 전체를 검토했으나 구체적인 제품·작품·행사·기술·행동 또는 촉발 사건을 확정하지 못함",
        "broad_category": None,
        "review_origin": "exhaustive_default_exclusion",
    }


def _policy_reason(reason_code: str) -> str | None:
    return {
        "policy_or_political_topic": "정치·선거·정책 중심 표현으로 홈 트렌드 범위에서 제외",
        "crime_or_personal_harm_topic": "범죄·사망·개인 피해 중심 표현으로 제외",
        "disaster_or_accident_topic": "재난·사고 피해 중심 표현으로 제외",
    }.get(reason_code)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source", choices=("x", "google_trends"), required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--review-overlay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    review_decisions, review_metadata = _load_review_overlay(args.review_overlay, args.source)

    end = parse_at(args.observed_at)
    start = end - timedelta(hours=max(1, args.hours))
    minimum_rows = 30 if args.source == "x" else 100
    with sqlite3.connect(args.database) as connection:
        snapshots = connection.execute(
            """SELECT observed_at, COUNT(*) FROM hourly_observations
               WHERE source=? AND provenance='observed' AND observed_at BETWEEN ? AND ?
               GROUP BY observed_at ORDER BY observed_at""",
            (args.source, start.isoformat(), end.isoformat()),
        ).fetchall()
        if args.source == "x":
            valid_times = [observed_at for observed_at, count in snapshots if int(count) == 30]
        else:
            valid_times = [observed_at for observed_at, count in snapshots if int(count) >= minimum_rows]
        placeholders = ",".join("?" for _ in valid_times) or "NULL"
        rows = connection.execute(
            f"""SELECT observed_at, topic, source_rank FROM hourly_observations
                WHERE source=? AND provenance='observed' AND observed_at IN ({placeholders})
                ORDER BY observed_at, source_rank, topic""",
            (args.source, *valid_times),
        ).fetchall() if valid_times else []

    grouped: dict[str, dict[str, object]] = {}
    end_iso = end.isoformat()
    for observed_at, topic, rank in rows:
        display_name = " ".join(str(topic or "").strip().split())
        key = normalize_event_key(display_name)
        record = grouped.setdefault(key, {
            "display_name": display_name,
            "raw_terms": set(),
            "observations": [],
        })
        record["raw_terms"].add(display_name)
        record["observations"].append((str(observed_at), int(rank)))

    topics: list[dict] = []
    first_pass_not_selected_count = 0
    explicit_review_count = 0
    default_exclusion_count = 0
    for key, record in grouped.items():
        observations = record["observations"]
        raw_terms = sorted(record["raw_terms"])
        # The first observed spelling is only presentation.  The event key and
        # all raw variants remain in the audit record.
        first_pass = adjudicate_source_expression(str(record["display_name"])).as_dict()
        if first_pass["decision"] == "not_selected":
            first_pass_not_selected_count += 1
        explicit_review = review_decisions.get(key)
        if explicit_review:
            explicit_review_count += 1
            adjudication = {
                **first_pass,
                **explicit_review,
                "finality": "final_after_exhaustive_context_review",
                "ranking_effect": "none",
            }
        elif first_pass["decision"] == "not_selected":
            default_exclusion_count += 1
            adjudication = {
                **_final_exclusion(first_pass),
                "finality": "final_after_exhaustive_context_review",
                "ranking_effect": "none",
            }
        else:
            adjudication = {
                **first_pass,
                "canonical_name": record["display_name"],
                "reason": _policy_reason(str(first_pass["reason_code"])),
                "review_origin": "deterministic_first_pass",
            }
        if not adjudication.get("canonical_name"):
            adjudication["canonical_name"] = record["display_name"]
        latest = [rank for observed_at, rank in observations if observed_at == end_iso]
        topics.append({
            "display_name": record["display_name"],
            "normalized_event_key": key,
            "raw_terms": raw_terms,
            "observed_hours": len({observed_at for observed_at, _ in observations}),
            "best_source_rank": min(rank for _, rank in observations),
            "latest_source_rank": min(latest) if latest else None,
            "is_current": bool(latest),
            "source": args.source,
            "first_pass_decision": first_pass["decision"],
            "first_pass_reason_code": first_pass["reason_code"],
            "_observation_times": sorted({observed_at for observed_at, _ in observations}),
            **adjudication,
        })

    # This order is audit-only.  It is never a public trend rank.
    topics.sort(key=lambda row: (
        {"included": 0, "excluded": 1}[row["decision"]],
        -row["observed_hours"], row["best_source_rank"], row["display_name"].casefold(),
    ))

    merged: dict[str, dict] = {}
    for row in (item for item in topics if item["decision"] == "included"):
        canonical_name = str(row.get("canonical_name") or row["display_name"])
        canonical_key = normalize_event_key(canonical_name)
        event = merged.setdefault(canonical_key, {
            "canonical_name": canonical_name,
            "normalized_event_key": canonical_key,
            "source": args.source,
            "decision": "included",
            "broad_category": row["broad_category"],
            "source_expressions": set(),
            "raw_terms": set(),
            "observation_times": set(),
            "best_source_rank": row["best_source_rank"],
            "latest_source_rank": row["latest_source_rank"],
            "is_current": row["is_current"],
            "reason_codes": set(),
            "review_reasons": set(),
            "review_origins": set(),
            "evidence": set(),
            "ranking_effect": "none",
            "finality": "final_after_exhaustive_context_review",
        })
        if event["broad_category"] != row["broad_category"]:
            raise ValueError(f"category conflict while merging {canonical_name}")
        event["source_expressions"].add(row["display_name"])
        event["raw_terms"].update(row["raw_terms"])
        event["observation_times"].update(row["_observation_times"])
        event["best_source_rank"] = min(event["best_source_rank"], row["best_source_rank"])
        if row["latest_source_rank"] is not None:
            current_latest = event["latest_source_rank"]
            event["latest_source_rank"] = row["latest_source_rank"] if current_latest is None else min(current_latest, row["latest_source_rank"])
        event["is_current"] = event["is_current"] or row["is_current"]
        event["reason_codes"].add(row["reason_code"])
        if row.get("reason"):
            event["review_reasons"].add(row["reason"])
        event["review_origins"].add(row["review_origin"])
        event["evidence"].update(row.get("evidence") or [])

    included: list[dict] = []
    for event in merged.values():
        observation_times = sorted(event.pop("observation_times"))
        event["observed_hours"] = len(observation_times)
        event["first_observed_at"] = observation_times[0]
        event["last_observed_at"] = observation_times[-1]
        event["member_expression_count"] = len(event["source_expressions"])
        for field in ("source_expressions", "raw_terms", "reason_codes", "review_reasons", "review_origins", "evidence"):
            event[field] = sorted(event[field], key=str.casefold)
        included.append(event)
    included.sort(key=lambda row: (
        -row["observed_hours"], row["best_source_rank"], row["canonical_name"].casefold(),
    ))

    for row in topics:
        row.pop("_observation_times", None)
    final_counts = {state: sum(row["decision"] == state for row in topics) for state in ("included", "excluded")}
    unmatched_review_keys = sorted(set(review_decisions) - set(grouped))
    result = {
        "schema_version": "trzip-single-source-final-adjudication-v2",
        "policy_version": POLICY_VERSION,
        "source": args.source,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "hours": args.hours},
        "valid_snapshot_rule": "exactly_30_x_ranks" if args.source == "x" else "complete_google_ranking_at_least_100_rows",
        "valid_snapshots": len(valid_times),
        "observed_source_rows": len(rows),
        "decision_contract": {
            "included": "Concrete phenomenon included after deterministic rules and exhaustive expression review.",
            "excluded": "Final exclusion after policy checks or exhaustive review found no concrete trigger in the observed expression.",
            "review_states_remaining": 0,
            "every_expression_finally_decided": True,
            "external_research_used": False,
            "rank_effect": "none",
        },
        "review_audit": {
            **review_metadata,
            "first_pass_not_selected_count": first_pass_not_selected_count,
            "explicit_review_decision_count": explicit_review_count,
            "default_exclusion_count": default_exclusion_count,
            "matched_configured_terms": review_metadata["configured_terms"] - len(unmatched_review_keys),
            "unmatched_configured_term_keys": unmatched_review_keys,
            "default_exclusion_applied_only_to_first_pass_not_selected": True,
            "future_ranking_whitelist": False,
        },
        "final_counts": final_counts,
        "included_event_count_after_semantic_merge": len(included),
        "included_flow_candidates": included,
        "all_final_topics": topics,
    }
    sha256 = _write_json(args.output, result)
    print(json.dumps({
        "source": args.source,
        "valid_snapshots": len(valid_times),
        "observed_source_rows": len(rows),
        "unique_normalized_events": len(topics),
        "final_counts": final_counts,
        "included_event_count_after_semantic_merge": len(included),
        "review_states_remaining": 0,
        "every_expression_finally_decided": True,
        "unmatched_configured_terms": len(unmatched_review_keys),
        "sha256": sha256,
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
