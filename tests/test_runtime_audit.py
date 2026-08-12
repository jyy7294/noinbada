from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trzip.runtime_audit import audit_runtime


def _write_runtime(root: Path) -> None:
    latest = root / "publication" / "latest"
    latest.mkdir(parents=True)
    publication_id = "pub-test"
    generated_at = "2026-08-12T18:00:01+00:00"
    observed_at = "2026-08-12T18:00:00+00:00"
    company = {
        "company": "검증기업",
        "stock_code": "000001",
        "official_identity": {"status": "verified", "ranking_effect": "none"},
        "ontology_complete": True,
        "evidence_sources": [{"url": "https://example.com/evidence"}],
        "ontology_path": [
            {"review_status": "observed", "evidence_urls": ["https://example.com/source"]},
            {"review_status": "approved", "evidence_urls": ["https://example.com/evidence"]},
        ],
    }
    companies = [{**company, "stock_code": f"00000{index}"} for index in range(1, 6)]
    item = {
        "event_key": "event:test",
        "rank": 1,
        "display_name": "관측어",
        "score": 66.0,
        "score_components": {
            "rrf_points": 50.0,
            "momentum_points": 10.0,
            "persistence_points": 5.0,
            "cross_source_points": 1.0,
            "total_points": 66.0,
            "formula_version": "rrf60_momentum20_persistence15_cross5_v1",
            "rounding_policy": "each_component_2dp_then_sum_2dp",
        },
        "latest_source_ranks": {"x": 1, "google_trends": 1},
        "provenance": ["observed"],
        "lane": "main",
        "keywords": [
            {"text": f"관련어{index}", "affects_score": False} for index in range(1, 6)
        ],
        "companies": companies,
        "company_resolution": {
            "publish_status": "published",
            "minimum_gold_companies": 5,
        },
    }
    intelligence = {
        "schema_version": "trzip-intelligence-v3",
        "mode": "live",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "window": {"to": observed_at},
        "unified_ranking": [item],
        "public_top10": [item],
        "verification_policy": {"verification_affects_score": False},
        "verification_run": {"ranking_effect": "none"},
        "ranking_availability": {
            "current_sources": ["x", "google_trends"],
            "missing_sources": [],
            "is_combined_rank": True,
        },
    }
    metadata = {
        "schema_version": "trzip-live-data-v3",
        "mode": "live",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": observed_at,
    }
    status = {
        "schema_version": "trzip-runtime-status-v1",
        "mode": "live",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": observed_at,
    }
    for name, value in (
        ("intelligence", intelligence),
        ("metadata", metadata),
        ("status", status),
    ):
        (latest / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )

    db_path = root / "data" / "trzip-hourly.sqlite3"
    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE hourly_observations (
            observed_at TEXT NOT NULL,
            source TEXT NOT NULL,
            source_rank INTEGER NOT NULL,
            provenance TEXT NOT NULL,
            collector_version TEXT
        )
        """
    )
    for hour in range(96):
        observed = f"2026-08-{8 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00"
        for source, version in (("x", "x_current_session_v1"), ("google_trends", "google_trending_now_kr_v1")):
            connection.execute(
                "INSERT INTO hourly_observations VALUES (?, ?, 1, 'observed', ?)",
                (observed, source, version),
            )
    connection.commit()
    connection.close()


def test_runtime_audit_passes_complete_combined_runtime(tmp_path: Path) -> None:
    _write_runtime(tmp_path)

    result = audit_runtime(tmp_path)

    assert result["status"] == "pass"
    assert result["failures"] == []
    assert result["blockers"] == []
    assert result["metrics"]["clean_history_hours"] == 96


def test_runtime_audit_reports_provisional_without_x(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    intelligence_path = tmp_path / "publication" / "latest" / "intelligence.json"
    intelligence = json.loads(intelligence_path.read_text(encoding="utf-8"))
    intelligence["ranking_availability"] = {
        "current_sources": ["google_trends"],
        "missing_sources": ["x"],
        "is_combined_rank": False,
    }
    intelligence_path.write_text(json.dumps(intelligence), encoding="utf-8")
    connection = sqlite3.connect(tmp_path / "data" / "trzip-hourly.sqlite3")
    connection.execute("DELETE FROM hourly_observations WHERE source='x'")
    connection.commit()
    connection.close()

    result = audit_runtime(tmp_path)

    assert result["status"] == "provisional"
    assert "combined_x_google_not_ready" in result["blockers"]
    assert "x_v3_history_missing" in result["blockers"]


def test_runtime_audit_rejects_score_and_company_evidence_breakage(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    intelligence_path = tmp_path / "publication" / "latest" / "intelligence.json"
    intelligence = json.loads(intelligence_path.read_text(encoding="utf-8"))
    intelligence["unified_ranking"][0]["score"] = 99.0
    intelligence["public_top10"][0]["companies"][0]["ontology_path"] = []
    intelligence_path.write_text(json.dumps(intelligence), encoding="utf-8")

    result = audit_runtime(tmp_path)

    assert result["status"] == "fail"
    assert "score_component_mismatch" in result["failures"]
    assert "home_quality_gate_failed" in result["failures"]
