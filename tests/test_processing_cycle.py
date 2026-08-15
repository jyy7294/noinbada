from __future__ import annotations

import json
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
        companies.append({
            "company": f"Company {index}",
            "stock_code": f"C{index:03d}",
            "market": "KRX",
            "company_description": "Listed company description",
            "relationship_reason": "Documented relationship",
            "connection_explanation": "Public evidence explains the connection.",
            "evidence_sources": [{"url": f"https://example.com/company/{index}"}],
            "ontology_complete": True,
            "ontology_path": [{"from": "trend", "to": f"Company {index}"}],
            "company_role_category": role,
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
                "keyword": f"키워드{index + 1}",
                "company": f"Company {index}",
                "connection_explanation": "Public evidence explains the keyword link.",
                "evidence_urls": [f"https://example.com/company/{index}"],
            }
            for index in range(2)
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
    assert disabled["enrichment_batch"]["status"] == "disabled_missing_config"

    attempted = build_processing_cycle(
        {"unified_ranking": []},
        path=path,
        at=at,
        enrichment_checkpoint_executed=True,
        verification_status="disabled_missing_config",
        semantic_status="disabled_missing_config",
        handoff_status={"status": "exported_waiting_review"},
    )
    assert attempted["enrichment_batch"]["status"] == "attempted"
    assert attempted["enrichment_batch"]["component_status"] == {
        "naver_context": "disabled_missing_config",
        "semantic_llm": "disabled_missing_config",
        "review_handoff": "exported_waiting_review",
    }


def test_complete_card_gate_accepts_two_roles_and_rejects_one_role():
    observed_at = datetime(2026, 8, 15, 4, tzinfo=UTC)

    two_roles = complete_card_gate(
        _complete_candidate_with_role_count(2), observed_at=observed_at
    )
    one_role = complete_card_gate(
        _complete_candidate_with_role_count(1), observed_at=observed_at
    )

    assert two_roles["ready"] is True
    assert two_roles["checks"]["two_to_four_company_roles"] is True
    assert two_roles["role_category_count"] == 2
    assert one_role["ready"] is False
    assert one_role["checks"]["two_to_four_company_roles"] is False
    assert "two_to_four_company_roles" in one_role["missing"]
