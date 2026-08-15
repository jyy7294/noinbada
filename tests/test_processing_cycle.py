from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from trzip.hourly_store import HourlyObservation, store_verified_source_snapshot
from trzip.processing_cycle import (
    build_processing_cycle,
    checkpoint_due,
    complete_card_gate,
    observed_coverage_24h,
)


def _store_complete_hour(path, at):
    stamp = at.isoformat()
    x_rows = [
        HourlyObservation(
            stamp, "x", f"X{rank}", rank, 101 - rank, "observed",
            collector_version="x_current_session_kr_v1",
        )
        for rank in range(1, 31)
    ]
    google_payload = json.dumps({
        "collection_declared_total": 100,
        "collection_page_count": 4,
        "collection_completion_verified": True,
    })
    google_rows = [
        HourlyObservation(
            stamp, "google_trends", f"G{rank}", rank, 101 - rank, "observed",
            source_payload_json=google_payload,
            collector_version="google_trending_now_kr_v1",
        )
        for rank in range(1, 101)
    ]
    store_verified_source_snapshot(
        x_rows,
        source="x",
        collector="x_korea_realtime",
        detail="verified KR X snapshot",
        path=path,
    )
    store_verified_source_snapshot(
        google_rows,
        source="google_trends",
        collector="google_geo_kr",
        detail="verified complete Google KR snapshot",
        path=path,
    )


def _complete_candidate_with_role_count(role_count: int) -> dict:
    roles = [
        "manufacturing_development",
        "distribution",
        "retail_sales",
        "platform_service",
    ][:role_count]
    companies = []
    for index in range(10):
        role = roles[index % len(roles)]
        code = f"C{index:03d}"
        listing = {
            "status": "verified_current", "current_listed": True,
            "exchange": "KRX", "stock_code": code,
            "as_of": "2026-08-15", "evidence_owner": "KRX",
            "evidence_type": "exchange_current_security_universe",
            "evidence_url": "https://data.krx.co.kr/",
            "synthetic": False, "estimated": False, "ranking_effect": "none",
        }
        companies.append({
            "company": f"Company {index}",
            "stock_code": code,
            "market": "KRX",
            "company_description": "Listed company description",
            "relationship_reason": "Documented relationship",
            "connection_explanation": "Public evidence explains the connection.",
            "evidence_sources": [{"url": f"https://example.com/company/{index}"}],
            "ontology_complete": True,
            "ontology_path": [{"from": "trend", "to": f"Company {index}"}],
            "company_role_category": role,
            "matched_keywords": [f"키워드{index % 5 + 1}"],
            "listing_verification": listing,
            "market_reference": {
                "status": "observed", "provider": "pykrx",
                "source_url": "https://data.krx.co.kr/",
                "source_urls": {"fundamentals": "https://data.krx.co.kr/"},
                "field_sources": {
                    field: "https://data.krx.co.kr/"
                    for field in ("price_series", "market_cap_krw", "per", "pbr", "roe_pct")
                },
                "daily_ohlcv": [
                    {
                        "date": (
                            datetime(2026, 7, 17, tzinfo=UTC) + timedelta(days=day)
                        ).date().isoformat(),
                        "close": 100 + day,
                    }
                    for day in range(30)
                ],
                "summary": {
                    "as_of": "2026-08-15", "currency": "KRW",
                    "market_cap": 1_000_000, "market_cap_krw": 1_000_000,
                },
                "valuation": {
                    "per": 10.0,
                    "per_status": "observed",
                    "per_as_of": "2026-08-15",
                    "pbr": 1.0,
                    "pbr_as_of": "2026-08-15",
                    "roe_pct": 8.0,
                    "roe_numerator": {"as_of": "2026-08-15"},
                    "market_cap_as_of": "2026-08-15",
                },
                "fx_reference": {
                    "status": "observed", "provider": "identity", "rate": 1.0,
                    "as_of": "2026-08-15", "source_url": "https://data.krx.co.kr/",
                },
                "listing_verification": listing,
                "synthetic": False, "estimated": False, "ranking_effect": "none",
            },
        })
    return {
        "event_key": "role-contract",
        "lane": "main",
        "context_research": {
            "status": "ready",
            "trigger_title": "Documented trigger",
            "why_now": "A public source documents the current context.",
            "evidence_urls": ["https://example.com/context"],
        },
        "related_keywords": [
            {"text": text}
            for text in ("키워드1", "키워드2", "키워드3", "키워드4", "키워드5")
        ],
        "companies": companies,
        "keyword_company_links": [
            {
                "keyword": f"키워드{index % 5 + 1}",
                "company": f"Company {index}",
                "connection_explanation": "Public evidence explains the keyword link.",
                "evidence_urls": [f"https://example.com/company/{index}"],
            }
            for index in range(10)
        ],
        "series": [{
            "at": "2026-08-15T04:00:00+00:00",
            "source": "x",
            "value": 80,
            "provenance": "observed",
        }],
    }


def test_coverage_reports_missing_hours_without_fill_or_reuse(tmp_path):
    path = tmp_path / "hourly.sqlite3"
    at = datetime(2026, 8, 15, 4, tzinfo=UTC)
    _store_complete_hour(path, at - timedelta(hours=3))
    _store_complete_hour(path, at)

    coverage = observed_coverage_24h(path, at)

    assert coverage["status"] == "partial"
    assert coverage["dual_source_hour_count"] == 2
    assert coverage["missing_hour_count"] == 22
    assert coverage["missing_hour_policy"] == "allowed_no_fill_no_reuse"
    assert coverage["fabricated_hour_count"] == 0
    assert coverage["reused_previous_hour_count"] == 0
    assert coverage["ranking_uses_available_observed_hours_only"] is True


def test_checkpoint_schedule_and_actual_status_are_distinct(tmp_path):
    path = tmp_path / "hourly.sqlite3"
    at = datetime(2026, 8, 14, 19, tzinfo=UTC)  # 04:00 KST
    assert checkpoint_due(at)

    disabled = build_processing_cycle(
        {"unified_ranking": []},
        path=path,
        at=at,
        enrichment_checkpoint_executed=True,
        verification_status="disabled_missing_config",
        semantic_status="disabled_missing_config",
        handoff_status={"status": "not_configured"},
    )
    assert disabled["enrichment_batch"]["attempted"] is True
    assert disabled["enrichment_batch"]["status"] == (
        "completed_with_optional_components_disabled"
    )
    assert disabled["enrichment_batch"]["release_gate"]["release_ready"] is True
    assert disabled["enrichment_batch"]["component_execution"]["semantic_llm"][
        "status"
    ] == "disabled_missing_config"

    attempted = build_processing_cycle(
        {"unified_ranking": []},
        path=path,
        at=at + timedelta(hours=4),
        enrichment_checkpoint_executed=True,
        verification_status="disabled_missing_config",
        semantic_status="disabled_missing_config",
        handoff_status={"status": "exported_waiting_review"},
    )
    assert attempted["enrichment_batch"]["status"] == (
        "completed_with_deferred_work_and_optional_components_disabled"
    )
    assert attempted["enrichment_batch"]["component_status"] == {
        "naver_context": "disabled_missing_config",
        "semantic_llm": "disabled_missing_config",
        "approved_cache": "empty",
        "review_handoff": "exported_waiting_review",
        "complete_card_gate": "completed",
    }
    assert attempted["enrichment_batch"]["component_execution"]["review_handoff"][
        "status"
    ] == "deferred"
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT observed_at,summary_json FROM enrichment_checkpoints ORDER BY observed_at"
        ).fetchall()
    assert len(rows) == 2
    stored = json.loads(rows[-1][1])
    assert stored["release_gate"]["checkpoint_recorded"] is True
    assert stored["component_execution"]["semantic_llm"]["status"] == (
        "disabled_missing_config"
    )
    assert stored["component_execution"]["review_handoff"]["status"] == "deferred"


def test_complete_card_gate_accepts_three_roles_and_rejects_two_roles():
    observed_at = datetime(2026, 8, 15, 4, tzinfo=UTC)

    three_roles = complete_card_gate(
        _complete_candidate_with_role_count(3), observed_at=observed_at
    )
    two_roles = complete_card_gate(
        _complete_candidate_with_role_count(2), observed_at=observed_at
    )

    assert three_roles["ready"] is True
    assert three_roles["checks"]["three_to_four_company_roles"] is True
    assert three_roles["role_category_count"] == 3
    assert two_roles["ready"] is False
    assert two_roles["checks"]["three_to_four_company_roles"] is False
    assert "three_to_four_company_roles" in two_roles["missing"]
