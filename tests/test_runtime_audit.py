from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trzip.runtime_audit import audit_runtime
from trzip.publication_pipeline import _write_frontend_delivery


def _write_runtime(root: Path) -> None:
    latest = root / "publication" / "latest"
    latest.mkdir(parents=True)
    publication_id = "pub-" + ("a" * 32)
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
        "main_rank": 1,
        "display_name": "관측어",
        "score": 72.0,
        "score_components": {
            "period_strength_points": 32.0,
            "momentum_points": 10.0,
            "persistence_points": 10.0,
            "recency_points": 15.0,
            "cross_source_points": 5.0,
            "total_points": 72.0,
            "formula_version": "period40_momentum20_persistence20_recency15_cross5_v1",
            "rounding_policy": "each_component_2dp_then_sum_2dp",
        },
        "candidate_status": "is_current",
        "is_current": True,
        "period_sources": ["x", "google_trends"],
        "period_strength": 0.8,
        "freshness": {
            "signal": 1.0,
            "half_life_hours": 84.0,
            "hours_since_last_seen": 0.0,
        },
        "hours_since_last_seen": 0.0,
        "last_seen_at": observed_at,
        "detail_status": "shared_full_detail",
        "latest_source_ranks": {"x": 1, "google_trends": 1},
        "provenance": ["observed"],
        "lane": "main",
        "company_card_status": "ready",
        "company_card_reason": "evidence_backed_five_or_more",
        "keywords": [
            {"text": f"관련어{index}", "affects_score": False} for index in range(1, 6)
        ],
        "companies": companies,
        "company_resolution": {
            "publish_status": "published",
            "minimum_gold_companies": 5,
        },
    }
    period_item = {
        key: value
        for key, value in item.items()
        if key not in {"companies"}
    }
    period_item.update({
        "topic": "관측어",
        "broad_category": "culture",
        "category": "culture",
        "current_source_position": 1.0,
        "momentum": 0.5,
        "persistence": 0.5,
        "lifecycle": "sustained",
        "lifecycle_reason": "repeated_observation",
        "first_seen_at": "2026-08-08T19:00:00+00:00",
        "last_seen_at": observed_at,
        "rank_change_by_source": {"x": 0, "google_trends": 0},
        "source_badge": "교차출처",
        "data_confidence": {"level": "high"},
        "ranking_data_readiness": {"status": "ready"},
        "detail_event_key": "event:test",
        "shared_detail_fields": ["keywords", "companies"],
    })
    period_definitions = [("daily", "24시간", 24), ("weekly", "7일", 168), ("monthly", "30일", 720)]
    ranking_periods = [
        {
            "key": key,
            "label": label,
            "default": key == "weekly",
            "window": {
                "from": observed_at,
                "to": observed_at,
                "hours": hours,
                "score_history_hours": hours,
                "lifecycle_baseline_days": 60,
            },
        }
        for key, label, hours in period_definitions
    ]
    ranking_views = {}
    for period in ranking_periods:
        view_item = json.loads(json.dumps(period_item))
        view_item["freshness"]["half_life_hours"] = period["window"]["hours"] / 2
        ranking_views[period["key"]] = {
            **period,
            "formula_version": "period40_momentum20_persistence20_recency15_cross5_v1",
            "data_readiness": {"status": "ready"},
            "company_detail_policy": "shared_by_detail_event_key",
            "company_count_affects_rank": False,
            "unified_ranking": [view_item],
            "period_top10": [dict(view_item)],
        }
    intelligence = {
        "schema_version": "trzip-intelligence-v3",
        "mode": "live",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "window": {"to": observed_at},
        "ranking_default_period": "weekly",
        "ranking_periods": ranking_periods,
        "ranking_views": ranking_views,
        "ranking_top_level_alias": {
            "period": "weekly",
            "unified_ranking": "weekly_period_aggregate",
            "trend_top10": "weekly_period_top10",
        },
        "unified_ranking": [item],
        "trend_top10": [item],
        "public_top10": [item],
        "company_ready_trends": [item],
        "verification_policy": {"verification_affects_score": False},
        "verification_run": {"ranking_effect": "none"},
        "collection_status": {
            "source_status": {"x": "observed", "google_trends": "observed"},
            "partial": False,
        },
        "daily_aggregates": [],
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
        "collection": {
            "observed": 130,
            "audit": {
                "x_korea_realtime": {
                    "status": "observed",
                    "row_count": 30,
                    "collector": "codex_chrome_current_session",
                    "transport": "codex_browser_snapshot",
                    "profile": "current_logged_in_chrome",
                },
                "google_geo_kr": {
                    "status": "observed",
                    "row_count": 100,
                    "declared_total": 100,
                    "page_count": 4,
                    "completion_verified": True,
                },
            },
        },
        "coverage": {
            "first_hour": "2026-08-08T19:00:00+00:00",
            "last_hour": observed_at,
            "hours": 96,
            "rows": 12480,
            "observed_rows": 12480,
        },
    }
    status = {
        "schema_version": "trzip-runtime-status-v1",
        "mode": "live",
        "publication_id": publication_id,
        "generated_at": generated_at,
        "observed_at": observed_at,
        "source_status": {"x": "observed", "google_trends": "observed"},
        "partial": False,
    }
    for name, value in (
        ("intelligence", intelligence),
        ("metadata", metadata),
        ("status", status),
    ):
        (latest / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )
    _write_frontend_delivery(
        root / "publication",
        intelligence,
        metadata,
        status,
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
    last_hour = datetime.fromisoformat(observed_at)
    for offset in range(95, -1, -1):
        observed = (last_hour - timedelta(hours=offset)).isoformat()
        for source, count, version in (
            ("x", 30, "x_current_session_kr_v1"),
            ("google_trends", 100, "google_trending_now_kr_v1"),
        ):
            for rank in range(1, count + 1):
                connection.execute(
                    "INSERT INTO hourly_observations VALUES (?, ?, ?, 'observed', ?)",
                    (observed, source, rank, version),
                )
    connection.commit()
    connection.close()


def _refresh_frontend_delivery(root: Path) -> None:
    latest = root / "publication" / "latest"
    documents = {
        name: json.loads((latest / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("intelligence", "metadata", "status")
    }
    _write_frontend_delivery(
        root / "publication",
        documents["intelligence"],
        documents["metadata"],
        documents["status"],
    )


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
    intelligence["collection_status"] = {
        "source_status": {"x": "current_session_not_ready", "google_trends": "observed"},
        "partial": True,
    }
    intelligence_path.write_text(json.dumps(intelligence), encoding="utf-8")
    metadata_path = tmp_path / "publication" / "latest" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["collection"]["observed"] = 100
    metadata["collection"]["audit"]["x_korea_realtime"] = {
        "status": "current_session_not_ready",
        "row_count": 0,
    }
    metadata["coverage"]["rows"] = 9600
    metadata["coverage"]["observed_rows"] = 9600
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    status_path = tmp_path / "publication" / "latest" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["source_status"] = {
        "x": "current_session_not_ready",
        "google_trends": "observed",
    }
    status["partial"] = True
    status_path.write_text(json.dumps(status), encoding="utf-8")
    connection = sqlite3.connect(tmp_path / "data" / "trzip-hourly.sqlite3")
    connection.execute("DELETE FROM hourly_observations WHERE source='x'")
    connection.commit()
    connection.close()
    _refresh_frontend_delivery(tmp_path)

    result = audit_runtime(tmp_path)

    assert result["status"] == "provisional"
    assert "combined_x_google_not_ready" in result["blockers"]
    assert "x_v3_history_missing" in result["blockers"]


def test_runtime_audit_rejects_score_and_company_evidence_breakage(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    intelligence_path = tmp_path / "publication" / "latest" / "intelligence.json"
    intelligence = json.loads(intelligence_path.read_text(encoding="utf-8"))
    intelligence["unified_ranking"][0]["score"] = 99.0
    intelligence["ranking_views"]["weekly"]["unified_ranking"][0]["score"] = 99.0
    intelligence["ranking_views"]["weekly"]["period_top10"][0]["score"] = 99.0
    broken_companies = json.loads(json.dumps(intelligence["company_ready_trends"][0]["companies"]))
    broken_companies[0]["ontology_path"] = []
    intelligence["company_ready_trends"][0]["companies"] = broken_companies
    intelligence_path.write_text(json.dumps(intelligence), encoding="utf-8")
    _refresh_frontend_delivery(tmp_path)

    result = audit_runtime(tmp_path)

    assert result["status"] == "fail"
    assert "score_component_mismatch" in result["failures"]
    assert "company_ready_contract_failed" in result["failures"]


def test_runtime_audit_rejects_latest_provider_duplicate(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    connection = sqlite3.connect(tmp_path / "data" / "trzip-hourly.sqlite3")
    connection.executescript(
        """
        CREATE TABLE provider_verification_runs (
            id INTEGER PRIMARY KEY,
            observed_at TEXT,
            trend_key TEXT,
            provider TEXT,
            attempt_count INTEGER,
            ranking_effect TEXT
        );
        CREATE TABLE provider_verification_attempts (
            run_id INTEGER,
            quota_bucket TEXT,
            quota_cost INTEGER,
            started_at TEXT
        );
        INSERT INTO provider_verification_runs VALUES
          (1,'2026-08-12T18:00:00+00:00','event:test','youtube',0,'none'),
          (2,'2026-08-12T18:00:00+00:00','event:test','youtube',0,'none');
        """
    )
    connection.commit()
    connection.close()

    result = audit_runtime(tmp_path)

    assert result["status"] == "fail"
    assert "provider_verification_latest_hour_duplicate" in result["failures"]


def test_runtime_audit_rejects_non_allowlisted_collector_version(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    connection = sqlite3.connect(tmp_path / "data" / "trzip-hourly.sqlite3")
    connection.execute(
        "UPDATE hourly_observations SET collector_version='manual_backfill_v0' "
        "WHERE source='x' AND source_rank=1"
    )
    connection.commit()
    connection.close()

    result = audit_runtime(tmp_path)

    assert result["status"] == "fail"
    assert "collector_version_not_allowlisted" in result["failures"]
    assert result["metrics"]["invalid_collector_versions"] == [{
        "source": "x",
        "collector_version": "manual_backfill_v0",
    }]


def test_runtime_audit_rejects_frontend_bundle_tampering(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    manifest_path = tmp_path / "publication" / "latest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rankings_path = (
        tmp_path / "publication" / "latest" / manifest["bundle"]["rankings"]["path"]
    )
    rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
    rankings["unified_ranking"] = []
    rankings_path.write_text(json.dumps(rankings), encoding="utf-8")

    result = audit_runtime(tmp_path)

    assert result["status"] == "fail"
    assert "frontend_rankings_hash_mismatch" in result["failures"]
    assert "frontend_rankings_order_mismatch" in result["failures"]
