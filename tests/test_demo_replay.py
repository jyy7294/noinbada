import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from trzip.demo_replay import (
    _read_current_ledger,
    _resolve_reference_ranks,
    _score_at,
    build_demo_replay,
    validate_demo_replay,
)


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 8, 12, 23, tzinfo=UTC)


def test_demo_replay_is_deterministic_60d_and_separate_from_live(tmp_path):
    first = tmp_path / "first-demo"
    second = tmp_path / "second-demo"
    first_manifest = build_demo_replay(first, as_of=AT)
    second_manifest = build_demo_replay(second, as_of=AT)

    assert first_manifest["publication_id"] == second_manifest["publication_id"]
    assert first_manifest["bundle"]["rankings"]["sha256"] == second_manifest["bundle"]["rankings"]["sha256"]
    assert first_manifest["bundle"]["observation_ledger"]["sha256"] == second_manifest["bundle"]["observation_ledger"]["sha256"]

    latest = first / "latest"
    replay = json.loads((latest / "replay.json").read_text(encoding="utf-8"))
    rankings_path = latest / first_manifest["bundle"]["rankings"]["path"]
    rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
    assert replay["mode"] == rankings["mode"] == "demo_replay"
    assert replay["live_eligible"] is rankings["live_eligible"] is False
    assert rankings["score_window"]["days"] == 7
    assert rankings["lifecycle_baseline"]["days"] == 60
    assert len(rankings["daily_snapshots"]) == 60
    assert len(rankings["trend_top10"]) == 10
    assert rankings["public_top10"] == rankings["trend_top10"]
    assert rankings["default_view"] == "weekly"
    assert rankings["views"]["weekly"]["unified_ranking"] == rankings["unified_ranking"]
    assert rankings["views"]["weekly"]["trend_top10"] == rankings["trend_top10"]
    assert {
        name: view["window_hours"] for name, view in rankings["views"].items()
    } == {"daily": 24, "weekly": 168, "monthly": 720}
    assert replay["data_lineage"]["by_provenance"] == {
        "synthetic_backfill": replay["data_lineage"]["row_count"]
    }
    rankings_schema = json.loads(
        (ROOT / "schemas" / "demo-rankings-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(rankings_schema).validate(rankings)
    validate_demo_replay(first)


def test_demo_replay_preserves_observed_and_legacy_provenance(tmp_path):
    database = tmp_path / "ledger.sqlite3"
    import sqlite3

    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hourly_observations ("
        "observed_at TEXT, source TEXT, topic TEXT, source_rank INTEGER, value REAL, "
        "provenance TEXT, collector_version TEXT)"
    )
    connection.executemany(
        "INSERT INTO hourly_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (AT.isoformat(), "x", "실측 트렌드", 1, 100, "observed", "x_current_session_kr_v1"),
            (AT.isoformat(), "google_trends", "구글 실측", 2, 99, "observed", "google_trending_now_kr_v1"),
            (AT.isoformat(), "google_trends", "과거 참고", 1, 100, "observed", None),
        ],
    )
    connection.commit()
    connection.close()

    output = tmp_path / "demo"
    manifest = build_demo_replay(output, as_of=AT, live_database=database)
    ledger = output / "latest" / manifest["bundle"]["observation_ledger"]["path"]
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    measured = next(
        row for row in rows
        if row["topic"] == "실측 트렌드"
        and row["source"] == "x"
        and row["observed_at"] == AT.isoformat()
    )
    legacy = next(
        row for row in rows
        if row["topic"] == "과거 참고"
        and row["source"] == "google_trends"
        and row["observed_at"] == AT.isoformat()
    )
    google_measured = next(
        row for row in rows
        if row["topic"] == "구글 실측"
        and row["source"] == "google_trends"
        and row["observed_at"] == AT.isoformat()
    )
    assert measured["provenance"] == "observed"
    assert google_measured["provenance"] == "observed"
    assert legacy["provenance"] == "historical_reference"
    assert all(row["mode"] == "demo_replay" for row in rows)
    assert all(row["live_eligible"] is False for row in rows)


def test_demo_schema_and_live_root_guard(tmp_path, monkeypatch):
    schema = json.loads((ROOT / "schemas" / "demo-replay-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    observation_schema = json.loads(
        (ROOT / "schemas" / "demo-observation-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(observation_schema)
    rankings_schema = json.loads(
        (ROOT / "schemas" / "demo-rankings-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(rankings_schema)

    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    with pytest.raises(ValueError, match="outside live"):
        build_demo_replay(local / "TRZIP" / "publication" / "demo", as_of=AT)


def test_legacy_rows_preserve_values_and_resolve_duplicate_ranks(tmp_path):
    import sqlite3

    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE hourly_observations ("
        "observed_at TEXT, source TEXT, topic TEXT, source_rank INTEGER, value REAL, "
        "provenance TEXT, seed_observed_at TEXT, source_payload_json TEXT, "
        "related_terms_json TEXT, collector_version TEXT)"
    )
    connection.executemany(
        "INSERT INTO hourly_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (AT.isoformat(), "x", "나 트렌드", 2, 91, "observed", None, None, None, None),
            (AT.isoformat(), "x", "가 트렌드", 2, 92, "observed", None, None, None, None),
            (AT.isoformat(), "x", "다 트렌드", 3, 90, "observed", None, None, None, None),
        ],
    )
    connection.commit()
    connection.close()

    raw = _read_current_ledger(database, AT, 60)
    assert len(raw) == 3
    assert all(row["provenance"] == "historical_reference" for row in raw)
    assert all(row["legacy_operational"] is True for row in raw)
    assert [row["raw_rank"] for row in raw] == [2, 2, 3]
    assert [row["value"] for row in raw] == [91.0, 92.0, 90.0]
    assert raw[0]["field_lineage"]["region"] == "derived"
    assert raw[0]["field_lineage"]["collector_version"] == "unknown"
    assert raw[0]["field_lineage"]["related_terms"] == "not_collected"

    resolved = _resolve_reference_ranks(raw)
    assert [row["topic"] for row in resolved] == ["가 트렌드", "나 트렌드", "다 트렌드"]
    assert [row["raw_rank"] for row in resolved] == [2, 2, 3]
    assert [row["resolved_rank"] for row in resolved] == [1, 2, 3]
    assert resolved[0]["rank_resolution"] == "duplicate_raw_rank_resolved_by_event_key"
    assert resolved[2]["rank_resolution"] == "raw_rank_preserved"


def test_research_reconstruction_jsonl_is_separate_and_explicit(tmp_path):
    research = tmp_path / "research.jsonl"
    research.write_text(
        json.dumps({
            "observed_at": AT.isoformat(),
            "source": "x",
            "topic": "재구성 트렌드",
            "raw_rank": 4,
            "value": 80,
            "provenance": "reconstructed_reference",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "demo-research"
    manifest = build_demo_replay(
        output,
        as_of=AT,
        research_reconstruction_jsonl=research,
    )
    ledger = output / "latest" / manifest["bundle"]["observation_ledger"]["path"]
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    row = next(
        item for item in rows
        if item["topic"] == "재구성 트렌드"
        and item["source"] == "x"
        and item["observed_at"] == AT.isoformat()
    )
    assert row["provenance"] == "reconstructed_reference"
    assert row["measurement_status"] == "reconstructed_not_measured"
    assert row["live_eligible"] is False
    observation_schema = json.loads(
        (ROOT / "schemas" / "demo-observation-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(observation_schema).validate(row)


def test_research_event_seed_is_delivered_but_never_ranked(tmp_path):
    research = tmp_path / "research-events.jsonl"
    source = {
        "schema_version": "trzip-reconstructed-event-v1",
        "event_id": "sample-event",
        "representative_term": "샘플 트렌드",
        "aliases": ["샘플"],
        "category": "문화·생활",
        "active_from": "2026-07-01",
        "active_to": "2026-07-31",
        "peak_hint": "2026-07-15",
        "provenance": "research_reconstructed",
        "measurement_status": "event_timing_evidence_only",
        "rank_eligible": False,
        "confidence": 0.8,
        "evidence": [{
            "url": "https://example.com/evidence",
            "published_at": "2026-07-15",
            "publisher": "example",
            "evidence_type": "dated_report",
            "claim": "event timing only",
        }],
    }
    research.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
    output = tmp_path / "demo-research-events"
    manifest = build_demo_replay(
        output,
        as_of=AT,
        research_reconstruction_jsonl=research,
    )
    entry = manifest["bundle"]["research_event_catalog"]
    assert entry["row_count"] == 1
    catalog = output / "latest" / entry["path"]
    row = json.loads(catalog.read_text(encoding="utf-8").strip())
    assert row["provenance"] == "research_reconstructed"
    assert row["rank_eligible"] is False
    assert row["ranking_eligible"] is False
    assert row["ranking_effect"] == "none"
    rankings = json.loads(
        (output / "latest" / manifest["bundle"]["rankings"]["path"]).read_text(encoding="utf-8")
    )
    assert "sample-event" not in {item["event_key"] for item in rankings["unified_ranking"]}
    catalog_schema = json.loads(
        (ROOT / "schemas" / "demo-research-event-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(catalog_schema).validate(row)


def test_score_window_is_seven_days_but_lifecycle_baseline_uses_old_rows():
    old = AT - timedelta(days=30)
    rows = [
        {"observed_at": old.isoformat(), "source": "x", "event_key": "돌아온 트렌드", "source_rank": 1, "provenance": "historical_reference"},
        {"observed_at": AT.isoformat(), "source": "x", "event_key": "돌아온 트렌드", "source_rank": 1, "provenance": "observed"},
        {"observed_at": AT.isoformat(), "source": "google_trends", "event_key": "돌아온 트렌드", "source_rank": 1, "provenance": "observed"},
    ]
    result = _score_at(rows, at=AT, score_window_days=7)
    trend = result["ranking"][0]
    assert trend["lifecycle_baseline"]["first_seen_at"] == old.isoformat()
    assert trend["lifecycle"]["state"] == "rebounding"
    assert result["parameters"]["history_window_hours"] == 168
