"""Build an isolated, deterministic 60-day MVP replay for the frontend.

The replay deliberately never writes to the live SQLite ledger or the live
publication directory.  It can reuse eligible current observations and older
reference observations, but every row keeps its true provenance.  Gaps are
filled by a deterministic simulation so a frontend can exercise 60-day charts
before 60 days of the new collector have elapsed.

Only the newest seven days carry demo score weight.  The complete 60 days are
used for lifecycle labels and charts.  Live Ranking V2 is reused on an
ephemeral copy of the score-window rows; this module never relabels or persists
those copied rows as live observations.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .ranking_v2 import FORMULA_VERSION, build_ranking_v2


SCHEMA_VERSION = "trzip-demo-replay-v1"
OBSERVATION_SCHEMA_VERSION = "trzip-observation-v1"
RANKINGS_SCHEMA_VERSION = "trzip-rankings-v1"
TREND_SCHEMA_VERSION = "trzip-trend-detail-v1"
MANIFEST_SCHEMA_VERSION = "trzip-frontend-delivery-v1"
SEED_VERSION = "demo-replay-60d-v1"
PROVENANCE_VALUES = {
    "observed",
    "historical_reference",
    "reconstructed_reference",
    "synthetic_backfill",
}
RANK_SOURCES = ("x", "google_trends")
DEFAULT_TOPICS = (
    "말복", "나는 솔로", "지스타", "KBO", "러닝", "두바이 초콜릿",
    "폴더블폰", "아이폰", "업비트", "불꽃축제", "티빙", "삼성전자",
    "에코프로비엠", "야구", "K-pop", "무신사", "OTT", "게임스컴",
    "한강 수영장", "여름 휴가", "러닝크루", "프로야구", "갤럭시 Z",
    "넷플릭스", "치킨", "캠핑", "팝업스토어", "제로음료", "웹툰",
    "편의점 신제품", "숏폼", "챌린지", "공연", "페스티벌",
    "스포츠 굿즈", "콘서트", "여행", "AI 스마트폰", "전기차", "로봇",
)


def build_demo_replay(
    output_root: Path,
    *,
    as_of: datetime,
    live_database: Path | None = None,
    live_intelligence: Path | None = None,
    historical_databases: Sequence[Path] = (),
    fixture_series: Path | None = None,
    research_reconstruction_jsonl: Path | None = None,
    days: int = 60,
    score_window_days: int = 7,
) -> dict[str, Any]:
    """Create the separate manifest-last demo replay bundle.

    ``observed`` is reserved for rows from the current collector contract.
    Rows from older/unknown collectors are ``historical_reference`` and all
    generated gaps are ``synthetic_backfill``.  None can enter the live rank.
    """

    root = Path(output_root).resolve()
    _assert_isolated_demo_root(root)
    current_at = _floor_hour(as_of)
    if days != 60:
        raise ValueError("the MVP replay contract requires exactly 60 days")
    if score_window_days != 7:
        raise ValueError("the MVP replay score window requires exactly 7 days")

    templates, topic_order = _read_live_templates(live_intelligence)
    historical_rows = _read_current_ledger(live_database, current_at, days)
    for path in historical_databases:
        historical_rows.extend(_read_legacy_google(path, current_at, days))
    historical_rows.extend(
        _read_research_reconstruction(research_reconstruction_jsonl, current_at, days)
    )
    research_event_catalog = _read_research_event_catalog(
        research_reconstruction_jsonl, current_at, days
    )
    topic_order = _topic_catalog(topic_order, historical_rows)
    fixture_curve = _read_fixture_curve(fixture_series)

    observations = _materialise_observations(
        at=current_at,
        days=days,
        score_window_days=score_window_days,
        topics=topic_order,
        reference_rows=historical_rows,
        fixture_curve=fixture_curve,
    )
    ranking_views = {
        "daily": _ranking_view(observations, at=current_at, window_days=1, templates=templates),
        "weekly": _ranking_view(
            observations, at=current_at, window_days=score_window_days, templates=templates
        ),
        "monthly": _ranking_view(observations, at=current_at, window_days=30, templates=templates),
    }
    latest_ranking = ranking_views["weekly"]["_raw_current"]
    daily_snapshots = _daily_snapshots(
        observations,
        at=current_at,
        days=days,
        score_window_days=score_window_days,
    )
    publication_id = _publication_id(
        current_at, observations, reference_catalog=research_event_catalog
    )
    generated_at = current_at.isoformat()
    data_lineage = _lineage(observations)

    stage = root.parent / f".{root.name}.tmp"
    if stage.exists():
        shutil.rmtree(stage)
    if root.exists():
        shutil.rmtree(root)
    delivery = stage / "latest" / "delivery" / publication_id
    trends_dir = delivery / "trends"
    trends_dir.mkdir(parents=True)

    observation_path = delivery / "observations.ndjson"
    _write_ndjson(observation_path, observations)
    research_catalog_path = delivery / "research-events.ndjson"
    _write_ndjson(research_catalog_path, research_event_catalog)
    trend_index: list[dict[str, str]] = []
    summary_items: list[dict[str, Any]] = []
    all_series = _series_by_event(observations)
    current_source_ranks = _current_source_ranks(observations, current_at)
    previous_source_ranks = _current_source_ranks(
        observations, current_at - timedelta(hours=1)
    )
    period_by_event = {
        period: {
            item["event_key"]: item
            for item in view["unified_ranking"]
        }
        for period, view in ranking_views.items()
    }
    for scored in latest_ranking["ranking"]:
        event_key = scored["event_key"]
        template = templates.get(event_key, {})
        item = _trend_item(
            scored,
            template=template,
            series=all_series.get(event_key, []),
            current_source_ranks=current_source_ranks.get(event_key, {}),
            previous_source_ranks=previous_source_ranks.get(event_key, {}),
            publication_id=publication_id,
        )
        item["ranking_views"] = {
            period: period_by_event[period].get(event_key, {
                "rank": None,
                "score": None,
                "rank_change": None,
                "status": "not_current_candidate",
            })
            for period in ("daily", "weekly", "monthly")
        }
        weekly_period = item["ranking_views"]["weekly"]
        item["previous_period_rank"] = weekly_period.get("previous_period_rank")
        item["previous_period_score"] = weekly_period.get("previous_period_score")
        item["rank_change"] = weekly_period.get("rank_change")
        item["score_change"] = weekly_period.get("score_change")
        summary_items.append(_ranking_summary(item))
        filename = _trend_filename(event_key)
        detail_path = trends_dir / filename
        detail = {
            "schema_version": TREND_SCHEMA_VERSION,
            "publication_id": publication_id,
            "generated_at": generated_at,
            "observed_at": current_at.isoformat(),
            "mode": "demo_replay",
            "demo_label": "7일 순위 시뮬레이션 데모",
            "live_eligible": False,
            "ranking_effect": "none",
            "trend": item,
        }
        _write_json(detail_path, detail)
        trend_index.append({
            "event_key": event_key,
            "path": f"delivery/{publication_id}/trends/{filename}",
            "sha256": _sha256(detail_path),
        })

    top10 = summary_items[:10]
    public_views = {
        period: {
            key: value for key, value in view.items() if not key.startswith("_")
        }
        for period, view in ranking_views.items()
    }
    # Compatibility: the pre-view top-level ranking remains an exact alias of
    # the default weekly view, not a separately calculated list.
    public_views["weekly"]["unified_ranking"] = summary_items
    public_views["weekly"]["trend_top10"] = top10
    rankings = {
        "schema_version": RANKINGS_SCHEMA_VERSION,
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": current_at.isoformat(),
        "mode": "demo_replay",
        "demo_label": "7일 순위 시뮬레이션 데모",
        "live_eligible": False,
        "ranking_effect": "none",
        "data_window": {
            "days": days,
            "from": (current_at - timedelta(days=days) + timedelta(hours=1)).isoformat(),
            "to": current_at.isoformat(),
            "granularity": "daily baseline plus hourly recent score window",
        },
        "score_window": {
            "days": score_window_days,
            "hours": score_window_days * 24,
            "formula_version": FORMULA_VERSION,
            "same_formula_as_live": True,
        },
        "lifecycle_baseline": {"days": days, "ranking_effect": "none"},
        "default_view": "weekly",
        "views": public_views,
        "data_lineage": data_lineage,
        "research_event_catalog": {
            "path": f"delivery/{publication_id}/research-events.ndjson",
            "row_count": len(research_event_catalog),
            "provenance": "research_reconstructed",
            "measurement_status": "event_timing_evidence_only",
            "ranking_eligible": False,
            "ranking_effect": "none",
        },
        "unified_ranking": summary_items,
        "trend_top10": top10,
        "public_top10": top10,
        "company_ready_trends": [
            item for item in summary_items
            if item.get("company_card_status") == "ready"
        ],
        "daily_snapshots": daily_snapshots,
        "trend_detail_index": [
            {"event_key": item["event_key"], "path": item["path"]}
            for item in trend_index
        ],
    }
    rankings_path = delivery / "rankings.json"
    _write_json(rankings_path, rankings)

    replay = {
        "schema_version": SCHEMA_VERSION,
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": current_at.isoformat(),
        "mode": "demo_replay",
        "demo_label": "7일 순위 시뮬레이션 데모",
        "live_eligible": False,
        "ranking_effect": "none",
        "rank_sources": list(RANK_SOURCES),
        "data_window_days": days,
        "score_window_days": score_window_days,
        "lifecycle_baseline_days": days,
        "provenance_policy": {
            "allowed": sorted(PROVENANCE_VALUES),
            "observed": "current collector contract only",
            "historical_reference": "older measured asset; not current-contract live data",
            "reconstructed_reference": "research reconstruction; not a measured observation",
            "synthetic_backfill": "deterministic MVP gap fill; never measured",
            "row_level_provenance_preserved": True,
            "live_rank_insertion": "forbidden",
        },
        "data_lineage": data_lineage,
        "research_event_catalog": {
            "path": f"delivery/{publication_id}/research-events.ndjson",
            "row_count": len(research_event_catalog),
            "provenance": "research_reconstructed",
            "measurement_status": "event_timing_evidence_only",
            "ranking_eligible": False,
            "ranking_effect": "none",
        },
        "frontend_delivery": {
            "rankings_path": f"delivery/{publication_id}/rankings.json",
            "observation_ledger_path": f"delivery/{publication_id}/observations.ndjson",
            "research_event_catalog_path": f"delivery/{publication_id}/research-events.ndjson",
            "trend_detail_count": len(trend_index),
        },
    }
    replay_path = stage / "latest" / "replay.json"
    _write_json(replay_path, replay)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": current_at.isoformat(),
        "mode": "demo_replay",
        "demo_label": "7일 순위 시뮬레이션 데모",
        "live_eligible": False,
        "ranking_effect": "none",
        "documents": {
            "replay": {"path": "replay.json", "sha256": _sha256(replay_path)},
        },
        "bundle": {
            "path": f"delivery/{publication_id}",
            "rankings": {
                "path": f"delivery/{publication_id}/rankings.json",
                "sha256": _sha256(rankings_path),
            },
            "observation_ledger": {
                "path": f"delivery/{publication_id}/observations.ndjson",
                "sha256": _sha256(observation_path),
                "row_count": len(observations),
            },
            "research_event_catalog": {
                "path": f"delivery/{publication_id}/research-events.ndjson",
                "sha256": _sha256(research_catalog_path),
                "row_count": len(research_event_catalog),
                "ranking_eligible": False,
                "ranking_effect": "none",
            },
            "trend_count": len(trend_index),
            "trend_index": trend_index,
        },
    }
    manifest_path = stage / "latest" / "manifest.json"
    _write_json(manifest_path, manifest)  # manifest is intentionally written last
    stage.replace(root)
    validate_demo_replay(root)
    return manifest


def validate_demo_replay(root: Path) -> dict[str, Any]:
    """Validate hashes, identity, row provenance and demo/live isolation."""

    root = Path(root).resolve()
    manifest = _read_json(root / "latest" / "manifest.json", {})
    if manifest.get("mode") != "demo_replay" or manifest.get("live_eligible") is not False:
        raise ValueError("demo replay must be explicitly non-live")
    if manifest.get("ranking_effect") != "none":
        raise ValueError("demo replay cannot affect live ranking")
    latest = root / "latest"
    for entry in manifest.get("documents", {}).values():
        _validate_hash(latest, entry)
    bundle = manifest.get("bundle", {})
    _validate_hash(latest, bundle.get("rankings", {}))
    _validate_hash(latest, bundle.get("observation_ledger", {}))
    _validate_hash(latest, bundle.get("research_event_catalog", {}))
    for entry in bundle.get("trend_index", []):
        _validate_hash(latest, entry)

    rankings = _read_json(latest / bundle["rankings"]["path"], {})
    if rankings.get("mode") != "demo_replay" or rankings.get("live_eligible") is not False:
        raise ValueError("rankings payload is not isolated demo data")
    if len(rankings.get("daily_snapshots", [])) != 60:
        raise ValueError("demo replay requires 60 daily snapshots")
    if rankings.get("score_window", {}).get("days") != 7:
        raise ValueError("demo replay score window must be seven days")

    ledger = latest / bundle["observation_ledger"]["path"]
    row_count = 0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("provenance") not in PROVENANCE_VALUES:
            raise ValueError("observation ledger has invalid provenance")
        if row.get("mode") != "demo_replay" or row.get("live_eligible") is not False:
            raise ValueError("observation ledger contains a live-eligible row")
        row_count += 1
    if row_count != bundle["observation_ledger"]["row_count"]:
        raise ValueError("observation ledger row count mismatch")
    research_entry = bundle.get("research_event_catalog", {})
    research_path = latest / str(research_entry.get("path") or "")
    research_count = 0
    for line in research_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("provenance") != "research_reconstructed":
            raise ValueError("research event catalog contains invalid provenance")
        if row.get("rank_eligible") is not False or row.get("ranking_eligible") is not False:
            raise ValueError("research event catalog cannot be rank eligible")
        if row.get("mode") != "demo_replay" or row.get("live_eligible") is not False:
            raise ValueError("research event catalog contains a live-eligible row")
        if row.get("ranking_effect") != "none":
            raise ValueError("research event catalog cannot affect ranking")
        research_count += 1
    if research_count != research_entry.get("row_count"):
        raise ValueError("research event catalog row count mismatch")
    return manifest


def default_asset_paths() -> dict[str, Any]:
    """Return optional local assets without making any of them mandatory."""

    local = Path(os.environ.get("LOCALAPPDATA", "")) / "TRZIP"
    historical_root = Path.home() / "Documents" / "Codex" / "2026-08-05" / "roqk"
    candidates = [
        historical_root / "work" / "current-run.sqlite3",
        historical_root / "work" / "trzip-live-v5-20260809e.sqlite3",
    ]
    return {
        "live_database": local / "data" / "trzip-hourly.sqlite3",
        "live_intelligence": local / "publication" / "latest" / "intelligence.json",
        "historical_databases": [path for path in candidates if path.is_file()],
        "fixture_series": (
            historical_root / "frontend" / "contracts" / "trzip" / "responses"
            / "trend_series.json"
        ),
        "research_reconstruction_jsonl": None,
    }


def _assert_isolated_demo_root(root: Path) -> None:
    live_root = (Path(os.environ.get("LOCALAPPDATA", "")) / "TRZIP" / "publication").resolve()
    live_data_root = (Path(os.environ.get("LOCALAPPDATA", "")) / "TRZIP" / "live-data").resolve()
    for forbidden in (live_root, live_data_root):
        if root == forbidden or forbidden in root.parents or root in forbidden.parents:
            raise ValueError("demo replay output must be outside live publication and live-data roots")


def _read_current_ledger(path: Path | None, at: datetime, days: int) -> list[dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return []
    earliest = at - timedelta(days=days)
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(hourly_observations)")
        }
        if not {"observed_at", "source", "topic", "source_rank"} <= columns:
            return []
        selected = [
            "rowid AS legacy_rowid", "observed_at", "source", "topic",
            "source_rank", "value", "provenance",
        ]
        selected.append("seed_observed_at" if "seed_observed_at" in columns else "NULL AS seed_observed_at")
        selected.append("source_payload_json" if "source_payload_json" in columns else "NULL AS source_payload_json")
        selected.append("related_terms_json" if "related_terms_json" in columns else "NULL AS related_terms_json")
        selected.append("collector_version" if "collector_version" in columns else "NULL AS collector_version")
        rows = connection.execute(
            f"SELECT {', '.join(selected)} FROM hourly_observations "
            "WHERE observed_at >= ? AND observed_at <= ? ORDER BY observed_at, source, source_rank",
            (earliest.isoformat(), at.isoformat()),
        )
        output = []
        for row in rows:
            source = _source(row["source"])
            if source is None:
                continue
            stamp = _parse_datetime(row["observed_at"])
            collector = str(row["collector_version"] or "")
            current_contract = collector in {
                "x_current_session_kr_v1", "google_trending_now_kr_v1"
            }
            raw_rank = int(row["source_rank"])
            value = float(row["value"]) if row["value"] is not None else None
            legacy_operational = not current_contract
            output.append({
                "schema_version": OBSERVATION_SCHEMA_VERSION,
                "observed_at": _floor_hour(stamp).isoformat(),
                "source": source,
                "region": "KR",
                "topic": str(row["topic"]).strip(),
                "event_key": _event_key(row["topic"]),
                "raw_rank": raw_rank,
                "source_rank": raw_rank,
                "resolved_rank": raw_rank,
                "value": value,
                "provenance": "observed" if current_contract else "historical_reference",
                "reference_kind": (
                    "current_collector_contract" if current_contract
                    else "legacy_operational_observed"
                ),
                "measurement_status": "measured",
                "legacy_operational": legacy_operational,
                "legacy_row_id": int(row["legacy_rowid"]),
                "collector_version": collector or None,
                "seed_observed_at": row["seed_observed_at"],
                "source_payload": _json_or_status(row["source_payload_json"]),
                "related_terms": _json_or_status(row["related_terms_json"]),
                "field_lineage": {
                    "observed_at": "observed",
                    "source": "observed",
                    "region": "derived",
                    "topic": "observed",
                    "event_key": "derived",
                    "raw_rank": "observed",
                    "source_rank": "observed_pending_tie_resolution",
                    "value": "observed" if value is not None else "unknown",
                    "collector_version": "observed" if collector else "unknown",
                    "seed_observed_at": (
                        "observed" if row["seed_observed_at"] else "not_collected"
                    ),
                    "source_payload": (
                        "observed" if row["source_payload_json"] else "not_collected"
                    ),
                    "related_terms": (
                        "observed" if row["related_terms_json"] else "not_collected"
                    ),
                },
            })
        return output
    finally:
        connection.close()


def _read_legacy_google(path: Path, at: datetime, days: int) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    earliest = at - timedelta(days=days)
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "raw_signals" not in tables:
            return []
        records = connection.execute(
            "SELECT observed_at, title, metric_value FROM raw_signals "
            "WHERE platform = 'google-trending-now' ORDER BY observed_at, title"
        ).fetchall()
        grouped: dict[datetime, list[sqlite3.Row]] = defaultdict(list)
        for row in records:
            stamp = _floor_hour(_parse_datetime(row["observed_at"]))
            if earliest <= stamp <= at and str(row["title"] or "").strip():
                grouped[stamp].append(row)
        output: list[dict[str, Any]] = []
        for stamp, rows in sorted(grouped.items()):
            rows = sorted(
                rows,
                key=lambda row: (-float(row["metric_value"] or 0), str(row["title"])),
            )
            for rank, row in enumerate(rows, 1):
                topic = str(row["title"]).strip()
                output.append({
                    "schema_version": OBSERVATION_SCHEMA_VERSION,
                    "observed_at": stamp.isoformat(),
                    "source": "google_trends",
                    "region": "KR",
                    "topic": topic,
                    "event_key": _event_key(topic),
                    "raw_rank": rank,
                    "source_rank": rank,
                    "resolved_rank": rank,
                    "value": float(row["metric_value"] or 0),
                    "provenance": "historical_reference",
                    "reference_kind": "legacy_google_trending_asset_rank_inferred",
                    "measurement_status": "measured_legacy_asset",
                    "legacy_operational": False,
                    "collector_version": None,
                    "seed_observed_at": None,
                    "source_payload": {"status": "not_collected", "value": None},
                    "related_terms": {"status": "not_collected", "value": None},
                    "field_lineage": {
                        "observed_at": "observed",
                        "source": "observed",
                        "region": "derived",
                        "topic": "observed",
                        "event_key": "derived",
                        "raw_rank": "derived_from_metric_order",
                        "source_rank": "derived_from_metric_order",
                        "value": "observed",
                        "collector_version": "unknown",
                        "seed_observed_at": "not_collected",
                        "source_payload": "not_collected",
                        "related_terms": "not_collected",
                    },
                })
        return output
    finally:
        connection.close()


def _read_research_reconstruction(
    path: Path | None,
    at: datetime,
    days: int,
) -> list[dict[str, Any]]:
    """Read an optional, explicitly reconstructed JSONL reference input.

    The extension point is fail-closed: every record must self-identify as a
    reconstruction and may only use X or Google.  It is never upgraded to
    measured or current-contract provenance.
    """

    if path is None or not Path(path).is_file():
        return []
    earliest = at - timedelta(days=days)
    output: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            source_row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"research reconstruction JSONL line {line_number} is invalid") from exc
        provenance = source_row.get("provenance")
        if provenance == "research_reconstructed":
            # Event-timing research seeds have no measured platform or rank.
            # They are delivered through the separate non-ranking catalog.
            continue
        if provenance not in {"reconstructed_reference", "research_reconstruction"}:
            raise ValueError(
                f"research reconstruction line {line_number} must declare reconstructed provenance"
            )
        source = _source(source_row.get("source"))
        if source is None:
            raise ValueError(f"research reconstruction line {line_number} has unsupported source")
        stamp = _floor_hour(_parse_datetime(source_row.get("observed_at")))
        if stamp < earliest or stamp > at:
            continue
        topic = str(source_row.get("topic") or "").strip()
        if not topic:
            raise ValueError(f"research reconstruction line {line_number} has no topic")
        raw_rank = source_row.get("raw_rank", source_row.get("source_rank"))
        try:
            raw_rank = int(raw_rank)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"research reconstruction line {line_number} has no valid rank") from exc
        if raw_rank < 1:
            raise ValueError(f"research reconstruction line {line_number} has no valid rank")
        value = source_row.get("value")
        output.append({
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "observed_at": stamp.isoformat(),
            "source": source,
            "region": str(source_row.get("region") or "KR"),
            "topic": topic,
            "event_key": _event_key(source_row.get("event_key") or topic),
            "raw_rank": raw_rank,
            "source_rank": raw_rank,
            "resolved_rank": raw_rank,
            "value": float(value) if value is not None else None,
            "provenance": "reconstructed_reference",
            "reference_kind": "research_reconstruction_jsonl",
            "measurement_status": "reconstructed_not_measured",
            "legacy_operational": False,
            "collector_version": source_row.get("collector_version"),
            "seed_observed_at": source_row.get("seed_observed_at"),
            "source_payload": _status_value(source_row.get("source_payload")),
            "related_terms": _status_value(source_row.get("related_terms")),
            "research_input_line": line_number,
            "field_lineage": {
                "observed_at": "reconstructed",
                "source": "reconstructed",
                "region": "reconstructed" if source_row.get("region") else "derived",
                "topic": "reconstructed",
                "event_key": "reconstructed" if source_row.get("event_key") else "derived",
                "raw_rank": "reconstructed",
                "source_rank": "reconstructed_pending_tie_resolution",
                "value": "reconstructed" if value is not None else "unknown",
                "collector_version": (
                    "reconstructed" if source_row.get("collector_version") else "unknown"
                ),
                "seed_observed_at": (
                    "reconstructed" if source_row.get("seed_observed_at") else "not_collected"
                ),
                "source_payload": (
                    "reconstructed" if source_row.get("source_payload") is not None else "not_collected"
                ),
                "related_terms": (
                    "reconstructed" if source_row.get("related_terms") is not None else "not_collected"
                ),
            },
        })
    return output


def _read_research_event_catalog(
    path: Path | None,
    at: datetime,
    days: int,
) -> list[dict[str, Any]]:
    """Read evidence-backed event timing seeds without inventing rank signals.

    These records deliberately lack a platform and rank.  They therefore stay
    outside the common observation ledger and are published as a sidecar
    catalog for normalization, QA and observed-term matching.  The original
    provenance and ``rank_eligible=false`` contract are preserved.
    """

    if path is None or not Path(path).is_file():
        return []
    window_start = (at - timedelta(days=days) + timedelta(hours=1)).date()
    window_end = at.date()
    output: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            source_row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"research reconstruction JSONL line {line_number} is invalid") from exc
        provenance = source_row.get("provenance")
        if provenance in {"reconstructed_reference", "research_reconstruction"}:
            continue
        if provenance != "research_reconstructed":
            raise ValueError(
                f"research event line {line_number} must declare research_reconstructed provenance"
            )
        if source_row.get("measurement_status") != "event_timing_evidence_only":
            raise ValueError(f"research event line {line_number} has invalid measurement status")
        if source_row.get("rank_eligible") is not False:
            raise ValueError(f"research event line {line_number} must be rank_eligible=false")
        representative_term = str(source_row.get("representative_term") or "").strip()
        event_id = str(source_row.get("event_id") or "").strip()
        if not representative_term or not event_id:
            raise ValueError(f"research event line {line_number} lacks identity")
        try:
            active_from = date.fromisoformat(str(source_row["active_from"]))
            active_to = date.fromisoformat(str(source_row["active_to"]))
            peak_hint = date.fromisoformat(str(source_row["peak_hint"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"research event line {line_number} has invalid dates") from exc
        if not active_from <= peak_hint <= active_to:
            raise ValueError(f"research event line {line_number} has peak outside active window")
        if any(key in source_row for key in ("search_volume", "platform_rank", "attention_index")):
            raise ValueError(f"research event line {line_number} contains fabricated rank metrics")
        row = dict(source_row)
        row.update({
            "research_input_line": line_number,
            "mode": "demo_replay",
            "live_eligible": False,
            "ranking_eligible": False,
            "ranking_effect": "none",
            "reference_kind": "research_event_timing_catalog",
            "replay_window": {
                "from": window_start.isoformat(),
                "to": window_end.isoformat(),
                "overlaps": active_from <= window_end and active_to >= window_start,
            },
        })
        output.append(row)
    return output


def _read_live_templates(path: Path | None) -> tuple[dict[str, dict], list[str]]:
    payload = _read_json(Path(path), {}) if path and Path(path).is_file() else {}
    templates: dict[str, dict] = {}
    order: list[str] = []
    for item in payload.get("unified_ranking", []):
        display = str(item.get("display_name") or item.get("topic") or "").strip()
        if not display:
            continue
        key = _event_key(item.get("event_key") or display)
        templates[key] = item
        order.append(display)
    return templates, order


def _read_fixture_curve(path: Path | None) -> list[float]:
    payload = _read_json(Path(path), {}) if path and Path(path).is_file() else {}
    series = (payload.get("trend_series") or {}).get("series") or []
    x_series = next((item for item in series if item.get("source_family") == "x"), {})
    values = [float(point.get("value") or 0) for point in x_series.get("points", [])]
    return values[-60:] if len(values) >= 60 else []


def _topic_catalog(live_topics: Iterable[str], references: Iterable[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for value in list(live_topics) + [row.get("topic", "") for row in references] + list(DEFAULT_TOPICS):
        topic = str(value or "").strip()
        key = _event_key(topic)
        if not topic or not key or key in seen:
            continue
        seen.add(key)
        values.append(topic)
    return values[:80]


def _materialise_observations(
    *,
    at: datetime,
    days: int,
    score_window_days: int,
    topics: Sequence[str],
    reference_rows: Sequence[Mapping[str, Any]],
    fixture_curve: Sequence[float],
) -> list[dict[str, Any]]:
    earliest_date = (at - timedelta(days=days - 1)).date()
    hourly_start = at - timedelta(days=score_window_days) + timedelta(hours=1)
    stamps = [
        datetime.combine(earliest_date + timedelta(days=index), time(at.hour), UTC)
        for index in range(days - score_window_days)
    ]
    stamps.extend(
        hourly_start + timedelta(hours=index)
        for index in range(score_window_days * 24)
    )
    stamps = sorted(set(stamps))
    references: dict[tuple[datetime, str], list[dict[str, Any]]] = defaultdict(list)
    for source_row in reference_rows:
        row = dict(source_row)
        stamp = _floor_hour(_parse_datetime(row["observed_at"]))
        source = _source(row["source"])
        if source in RANK_SOURCES and stamps[0] <= stamp <= at:
            row["observed_at"] = stamp.isoformat()
            row["source"] = source
            row["event_key"] = _event_key(row.get("event_key") or row.get("topic"))
            references[(stamp, source)].append(row)

    observations: list[dict[str, Any]] = []
    for stamp in stamps:
        day_index = (stamp.date() - earliest_date).days
        for source in RANK_SOURCES:
            observed = _resolve_reference_ranks(references.get((stamp, source), []))
            target_size = max(30, max((int(row["source_rank"]) for row in observed), default=0))
            used_keys = {row["event_key"] for row in observed}
            used_ranks = {int(row["source_rank"]) for row in observed}
            generated = _synthetic_snapshot(
                topics,
                stamp=stamp,
                source=source,
                day_index=day_index,
                fixture_curve=fixture_curve,
            )
            available_ranks = [rank for rank in range(1, target_size + 1) if rank not in used_ranks]
            synthetic_rows = []
            for topic, rank in zip(
                (topic for topic in generated if _event_key(topic) not in used_keys),
                available_ranks,
            ):
                synthetic_rows.append({
                    "schema_version": OBSERVATION_SCHEMA_VERSION,
                    "observed_at": stamp.isoformat(),
                    "source": source,
                    "region": "KR",
                    "topic": topic,
                    "event_key": _event_key(topic),
                    "raw_rank": None,
                    "source_rank": rank,
                    "resolved_rank": rank,
                    "value": float(target_size - rank + 1),
                    "provenance": "synthetic_backfill",
                    "reference_kind": "deterministic_gap_fill",
                    "measurement_status": "synthetic_not_measured",
                    "legacy_operational": False,
                    "collector_version": None,
                    "seed_observed_at": None,
                    "source_payload": {"status": "not_collected", "value": None},
                    "related_terms": {"status": "not_collected", "value": None},
                    "rank_resolution": "synthetic_generated_rank",
                    "ranking_eligible": True,
                    "field_lineage": {
                        "observed_at": "derived",
                        "source": "derived",
                        "region": "derived",
                        "topic": "synthetic",
                        "event_key": "derived",
                        "raw_rank": "not_collected",
                        "source_rank": "derived",
                        "value": "derived",
                        "collector_version": "not_collected",
                        "seed_observed_at": "not_collected",
                        "source_payload": "not_collected",
                        "related_terms": "not_collected",
                    },
                })
            for row in observed + synthetic_rows:
                row = dict(row)
                row.update({
                    "mode": "demo_replay",
                    "live_eligible": False,
                    "ranking_effect": "demo_replay_only",
                    "quality_status": "eligible",
                    "seed_version": SEED_VERSION,
                })
                observations.append(row)
    observations.sort(key=lambda row: (row["observed_at"], row["source"], row["source_rank"], row["event_key"]))
    return observations


def _synthetic_snapshot(
    topics: Sequence[str],
    *,
    stamp: datetime,
    source: str,
    day_index: int,
    fixture_curve: Sequence[float],
) -> list[str]:
    curve = fixture_curve[day_index % len(fixture_curve)] if fixture_curve else 1.0
    scored = []
    for index, topic in enumerate(topics):
        stable = _stable_unit(SEED_VERSION, source, topic)
        wave = _stable_unit(topic, stamp.date().isoformat())
        hour = _stable_unit(source, topic, str(stamp.hour))
        rotation = ((day_index * 7 + stamp.hour + index * 3) % 41) / 41
        score = stable * 0.35 + wave * 0.28 + hour * 0.12 + rotation * 0.2 + (curve % 17) / 340
        scored.append((score, topic))
    return [topic for _score, topic in sorted(scored, key=lambda item: (-item[0], _event_key(item[1])))]


def _score_at(observations: Sequence[Mapping[str, Any]], *, at: datetime, score_window_days: int) -> dict:
    score_rows = []
    for row in observations:
        stamp = _parse_datetime(row["observed_at"])
        if stamp <= at:
            # Ranking V2 fails closed on non-live provenance.  A private copy is
            # used solely for identical arithmetic; the original row and every
            # persisted output retain their honest demo provenance. Ranking V2
            # applies the seven-day persistence/history windows internally;
            # older rows are available only to its 60-day lifecycle baseline.
            score_rows.append({
                "observed_at": row["observed_at"],
                "source": row["source"],
                "event_key": row["event_key"],
                "source_rank": int(row["source_rank"]),
                "provenance": "observed",
                "quality_status": "eligible",
            })
    result = build_ranking_v2(
        score_rows,
        at=at,
        persistence_window_hours=score_window_days * 24,
        history_window_hours=score_window_days * 24,
        lifecycle_baseline_days=60,
        ranking_mode="live_observed",
    )
    result["ranking_mode"] = "demo_replay"
    result["live_eligible"] = False
    result["ranking_effect"] = "none"
    return result


def _ranking_view(
    observations: Sequence[Mapping[str, Any]],
    *,
    at: datetime,
    window_days: int,
    templates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one period view and compare it with the preceding equal period."""

    current = _score_at(observations, at=at, score_window_days=window_days)
    previous_at = at - timedelta(days=window_days)
    previous = _score_at(observations, at=previous_at, score_window_days=window_days)
    previous_by_event = {
        item["event_key"]: item for item in previous.get("ranking", [])
    }
    entries: list[dict[str, Any]] = []
    for item in current.get("ranking", []):
        old = previous_by_event.get(item["event_key"])
        template = templates.get(item["event_key"], {})
        display = str(
            template.get("display_name")
            or template.get("topic")
            or item["event_key"]
        )
        entries.append({
            "event_key": item["event_key"],
            "display_name": display,
            "rank": int(item["rank"]),
            "main_rank": int(item["rank"]),
            "score": float(item["score"]),
            "score_components": item["score_components"],
            "previous_period_rank": int(old["rank"]) if old else None,
            "previous_period_score": float(old["score"]) if old else None,
            "rank_change": (
                int(old["rank"]) - int(item["rank"])
                if old is not None else None
            ),
            "score_change": (
                round(float(item["score"]) - float(old["score"]), 2)
                if old is not None else None
            ),
            "status": "ranked",
        })
    return {
        "window_hours": window_days * 24,
        "window_days": window_days,
        "comparison": f"previous_{window_days}d_equal_window",
        "formula_version": current["formula_version"],
        "data_readiness": current["data_readiness"],
        "unified_ranking": entries,
        "trend_top10": entries[:10],
        "_raw_current": current,
    }


def _daily_snapshots(
    observations: Sequence[Mapping[str, Any]],
    *,
    at: datetime,
    days: int,
    score_window_days: int,
) -> list[dict[str, Any]]:
    dates = [(at - timedelta(days=offset)).date() for offset in reversed(range(days))]
    by_date: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        by_date[_parse_datetime(row["observed_at"]).date()].append(row)
    snapshots = []
    all_to_date: list[Mapping[str, Any]] = []
    for current_date in dates:
        all_to_date.extend(by_date.get(current_date, []))
        candidates = by_date.get(current_date, [])
        if not candidates:
            snapshots.append({"date": current_date.isoformat(), "top10": []})
            continue
        snapshot_at = max(_parse_datetime(row["observed_at"]) for row in candidates)
        ranking = _score_at(all_to_date, at=snapshot_at, score_window_days=score_window_days)
        snapshots.append({
            "date": current_date.isoformat(),
            "observed_at": snapshot_at.isoformat(),
            "top10": [
                {"rank": item["rank"], "event_key": item["event_key"], "score": item["score"]}
                for item in ranking["ranking"][:10]
            ],
        })
    return snapshots


def _trend_item(
    scored: Mapping[str, Any],
    *,
    template: Mapping[str, Any],
    series: Sequence[Mapping[str, Any]],
    current_source_ranks: Mapping[str, int],
    previous_source_ranks: Mapping[str, int],
    publication_id: str,
) -> dict[str, Any]:
    display = str(template.get("display_name") or template.get("topic") or scored["event_key"])
    provenance_counts = Counter(row["provenance"] for row in series)
    rank_change = {
        source: (
            previous_source_ranks[source] - rank
            if source in previous_source_ranks else None
        )
        for source, rank in current_source_ranks.items()
    }
    lifecycle_value = scored.get("lifecycle") or {}
    lifecycle = lifecycle_value.get("state", "new") if isinstance(lifecycle_value, dict) else lifecycle_value
    item = {
        "event_key": scored["event_key"],
        "display_name": display,
        "topic": display,
        "observed_representative_term": display,
        "display_name_policy": "observed_representative_term",
        "raw_terms": sorted({str(row.get("topic") or display) for row in series}),
        "rank": int(scored["rank"]),
        "main_rank": int(scored["rank"]),
        "status": "ranked",
        "score": float(scored["score"]),
        "score_components": scored["score_components"],
        "current_source_position": scored["signals"]["current"],
        "momentum": scored["signals"]["momentum"],
        "persistence": scored["signals"]["persistence"],
        "score_explanation": scored["score_explanation"],
        "source_metrics": scored["source_metrics"],
        "ranking_data_readiness": scored["data_readiness"],
        "lane": str(template.get("lane") or "main"),
        "category": str(template.get("category") or "unclassified"),
        "broad_category": str(template.get("broad_category") or "other"),
        "lifecycle": lifecycle,
        "lifecycle_label": lifecycle,
        "lifecycle_reason": lifecycle_value.get("reason_code") if isinstance(lifecycle_value, dict) else "demo_replay",
        "lifecycle_baseline": scored["lifecycle_baseline"],
        "first_seen_at": series[0]["observed_at"],
        "last_seen_at": series[-1]["observed_at"],
        "latest_source_ranks": dict(current_source_ranks),
        "rank_change_by_source": rank_change,
        "source_badge": "교차출처" if len(current_source_ranks) == 2 else "단일출처",
        "confidence": "demo",
        "data_confidence": {
            "level": "demo",
            "label": "7일 순위 시뮬레이션 데모",
            "reason": "실측·과거 참고·합성 백필을 구분한 MVP 재생 데이터",
        },
        "provenance": sorted(provenance_counts),
        "keywords": list(template.get("keywords") or [])[:5],
        "companies": list(template.get("companies") or []),
        "company_candidates": list(template.get("company_candidates") or []),
        "company_resolution": dict(template.get("company_resolution") or {}),
        "company_card_status": str(template.get("company_card_status") or "enrichment_pending"),
        "company_card_reason": str(template.get("company_card_reason") or "fewer_than_five_evidence_backed_companies"),
        "series": list(series),
        "data_provenance": {
            "counts": dict(sorted(provenance_counts.items())),
            "row_level_preserved": True,
            "mode": "demo_replay",
            "live_eligible": False,
            "ranking_effect": "none",
        },
        "frontend_detail_path": f"delivery/{publication_id}/trends/{_trend_filename(scored['event_key'])}",
    }
    return item


def _ranking_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "event_key", "display_name", "topic", "rank", "main_rank", "status", "score",
        "score_components", "lane", "category", "broad_category", "lifecycle",
        "lifecycle_reason", "first_seen_at", "last_seen_at", "latest_source_ranks",
        "rank_change_by_source", "source_badge", "confidence", "data_confidence",
        "company_resolution", "company_card_status", "company_card_reason",
        "data_provenance", "ranking_views", "previous_period_rank",
        "previous_period_score", "rank_change", "score_change",
        "frontend_detail_path",
    )
    return {key: item[key] for key in keys if key in item}


def _series_by_event(observations: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        result[row["event_key"]].append({
            "observed_at": row["observed_at"],
            "source": row["source"],
            "topic": row["topic"],
            "raw_rank": row.get("raw_rank"),
            "source_rank": row["source_rank"],
            "resolved_rank": row["resolved_rank"],
            "value": row["value"],
            "provenance": row["provenance"],
            "reference_kind": row["reference_kind"],
            "live_eligible": False,
        })
    for values in result.values():
        values.sort(key=lambda row: (row["observed_at"], row["source"], row["source_rank"]))
    return result


def _current_source_ranks(observations: Sequence[Mapping[str, Any]], at: datetime) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(dict)
    stamp = at.isoformat()
    for row in observations:
        if row["observed_at"] == stamp:
            result[row["event_key"]][row["source"]] = int(row["source_rank"])
    return result


def _lineage(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    provenance = Counter(row["provenance"] for row in observations)
    by_source = Counter(row["source"] for row in observations)
    by_source_provenance = Counter((row["source"], row["provenance"]) for row in observations)
    legacy_operational = Counter(
        row["source"] for row in observations if row.get("legacy_operational") is True
    )
    rank_resolution = Counter(row.get("rank_resolution", "unknown") for row in observations)
    return {
        "row_count": len(observations),
        "by_provenance": dict(sorted(provenance.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_source_and_provenance": {
            source: {
                provenance_name: by_source_provenance[(source, provenance_name)]
                for provenance_name in sorted(PROVENANCE_VALUES)
            }
            for source in RANK_SOURCES
        },
        "legacy_operational_observed_rows": {
            "total": sum(legacy_operational.values()),
            "by_source": {
                source: legacy_operational[source] for source in RANK_SOURCES
            },
            "values_preserved": True,
            "raw_rank_preserved": True,
            "duplicate_rank_policy": "raw_rank_then_event_key_then_topic_then_stable_row_id",
        },
        "rank_resolution_counts": dict(sorted(rank_resolution.items())),
        "measured_rows_are_not_synthetic": True,
        "synthetic_rows_are_not_claimed_as_measured": True,
    }


def _resolve_reference_ranks(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Preserve every source row and resolve duplicate raw ranks deterministically.

    Older operational snapshots contain multiple terms carrying the same rank.
    Dropping one would falsely reduce the measured ledger.  All rows therefore
    retain ``raw_rank`` and are sorted by raw rank, event identity, topic and a
    stable row identity before receiving a unique, continuous ``resolved_rank``.
    Duplicate event rows are also retained; Ranking V2 deterministically uses
    the best resolved rank for that event/source/hour.
    """

    materialised: list[dict[str, Any]] = []
    provenance_priority = {
        "observed": 0,
        "historical_reference": 1,
        "reconstructed_reference": 2,
        "synthetic_backfill": 3,
    }
    for ordinal, source_row in enumerate(rows):
        row = dict(source_row)
        key = _event_key(row.get("event_key") or row.get("topic"))
        if not key:
            continue
        provenance = row.get("provenance")
        if provenance not in PROVENANCE_VALUES:
            raise ValueError("reference row has invalid provenance")
        raw_rank = row.get("raw_rank", row.get("source_rank"))
        try:
            raw_rank = int(raw_rank)
        except (TypeError, ValueError) as exc:
            raise ValueError("reference row has no positive raw rank") from exc
        if raw_rank < 1:
            raise ValueError("reference row has no positive raw rank")
        row["event_key"] = key
        row["raw_rank"] = raw_rank
        row["_stable_ordinal"] = ordinal
        materialised.append(row)

    raw_rank_counts = Counter(row["raw_rank"] for row in materialised)
    event_counts = Counter(row["event_key"] for row in materialised)
    materialised.sort(
        key=lambda row: (
            row["raw_rank"],
            provenance_priority[row["provenance"]],
            row["event_key"],
            str(row.get("topic") or "").casefold(),
            int(row.get("legacy_row_id") or row.get("research_input_line") or row["_stable_ordinal"]),
        )
    )
    event_occurrence: Counter[str] = Counter()
    output: list[dict[str, Any]] = []
    for resolved_rank, row in enumerate(materialised, 1):
        event_occurrence[row["event_key"]] += 1
        duplicate_rank = raw_rank_counts[row["raw_rank"]] > 1
        duplicate_event = event_counts[row["event_key"]] > 1
        if duplicate_event and event_occurrence[row["event_key"]] > 1:
            resolution = "duplicate_event_secondary_resolved"
        elif duplicate_rank:
            resolution = "duplicate_raw_rank_resolved_by_event_key"
        elif resolved_rank != row["raw_rank"]:
            resolution = "rank_shift_after_prior_tie_resolution"
        else:
            resolution = "raw_rank_preserved"
        row["source_rank"] = resolved_rank
        row["resolved_rank"] = resolved_rank
        row["rank_resolution"] = resolution
        row["ranking_eligible"] = True
        row.setdefault("schema_version", OBSERVATION_SCHEMA_VERSION)
        row.setdefault("region", "KR")
        row.setdefault("field_lineage", {})["source_rank"] = (
            "observed" if resolution == "raw_rank_preserved" else "derived"
        )
        row.pop("_stable_ordinal", None)
        output.append(row)
    return output


def _source(value: Any) -> str | None:
    normalised = str(value or "").strip().lower()
    return {"x": "x", "google": "google_trends", "google_trends": "google_trends"}.get(normalised)


def _json_or_status(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {"status": "not_collected", "value": None}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {"status": "unknown", "value": None}
    return {"status": "observed", "value": parsed}


def _status_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "not_collected", "value": None}
    if isinstance(value, dict) and set(value) >= {"status", "value"}:
        return dict(value)
    return {"status": "reconstructed", "value": value}


def _event_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _stable_unit(*parts: str) -> float:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _publication_id(
    at: datetime,
    observations: Sequence[Mapping[str, Any]],
    *,
    reference_catalog: Sequence[Mapping[str, Any]] = (),
) -> str:
    digest = hashlib.sha256()
    digest.update(SEED_VERSION.encode("utf-8"))
    digest.update(at.isoformat().encode("utf-8"))
    for row in observations:
        digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for row in reference_catalog:
        digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return f"demo-{digest.hexdigest()[:32]}"


def _trend_filename(event_key: str) -> str:
    return f"trend-{hashlib.sha256(event_key.encode('utf-8')).hexdigest()[:24]}.json"


def _floor_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("all observation timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_ndjson(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_hash(root: Path, entry: Mapping[str, Any]) -> None:
    path = (root / str(entry.get("path") or "")).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("demo manifest path escapes output root") from exc
    if not path.is_file() or _sha256(path) != entry.get("sha256"):
        raise ValueError(f"demo manifest hash mismatch: {entry.get('path')}")
