from pathlib import Path
import json

from trzip.hourly_store import HourlyObservation, connect, upsert
from trzip.result_quality import _source_gate, evaluate_frontend_result


def _company(index: int) -> dict:
    return {
        "company": f"기업{index}",
        "stock_code": f"00000{index}",
        "market": "KRX",
        "company_description": "설명",
        "relationship_reason": "관계 이유",
        "company_role_category": "manufacturing_development",
        "company_role_label": "제조·개발",
        "ontology_complete": True,
        "ontology_path": [
            {"from": "event", "to": "industry"},
            {"from": "industry", "to": f"company-{index}"},
        ],
        "relation_tier": "direct",
        "evidence_sources": [{"url": f"https://example.com/{index}"}],
    }


def _trend(rank: int) -> dict:
    return {
        "publication_rank": rank,
        "event_key": f"event:{rank}",
        "display_name": f"트렌드 {rank}",
        "observed_rank": rank * 2,
        "broad_category": "technology",
        "trend_definition": "실측 데이터에서 관측된 구체적인 기술 트렌드입니다.",
        "frontend_readiness_status": "ready",
        "related_keywords": [
            {"text": f"키워드 {index}", "source": ["google_trends"]}
            for index in range(5)
        ],
        "companies": [_company(index) for index in range(1, 7)],
    }


def test_complete_frontend_result_passes_quality_gate():
    result = evaluate_frontend_result({"home_top10": [_trend(rank) for rank in range(1, 11)]})

    assert result["passed"] is True
    assert result["policy_version"] == "frontend-result-quality-v2"
    assert result["trend_count"] == 10
    assert all(row["keyword_count"] == 5 and row["company_count"] == 6 for row in result["trends"])


def test_quality_gate_rejects_missing_company_role_and_non_contiguous_rank():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["publication_rank"] = 7
    trends[1]["companies"][0].pop("company_role_category")

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert "publication_rank_not_contiguous" in result["failures"]
    assert any("incomplete_company" in failure for failure in result["failures"])


def test_quality_gate_rejects_mismatched_company_role_label():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["companies"][0]["company_role_label"] = "판매·리테일"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("invalid_company_role" in failure for failure in result["failures"])


def test_quality_gate_rejects_more_than_one_food_trend():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["broad_category"] = "food"
    trends[1]["broad_category"] = "food"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert "food_category_count:2" in result["failures"]


def test_quality_gate_rejects_duplicate_keyword_and_missing_trend_context():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["related_keywords"][1]["text"] = trends[0]["related_keywords"][0]["text"]
    trends[0]["trend_definition"] = ""
    trends[1]["broad_category"] = "other"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("empty_or_duplicate_keyword" in failure for failure in result["failures"])
    assert any("missing_trend_definition" in failure for failure in result["failures"])
    assert any("invalid_category" in failure for failure in result["failures"])


def test_source_gate_requires_contiguous_google_full_ranking(tmp_path: Path):
    database = tmp_path / "runtime.sqlite3"
    stamp = "2026-08-13T17:00:00+00:00"
    rows = [
        HourlyObservation(
            stamp, "x", f"x-{rank}", rank, 100 - rank, "observed",
            source_payload_json=json.dumps({
                "collector": "codex_chrome_current_session",
                "transport": "codex_browser_snapshot",
                "profile": "current_logged_in_chrome",
                "region": "KR", "region_verified": True,
                "observed_at": "2026-08-13T17:03:00+00:00",
                "scheduled_for": stamp, "schedule_delay_seconds": 180,
            }),
        )
        for rank in range(1, 31)
    ] + [
        HourlyObservation(stamp, "google_trends", f"g-{rank}", rank, 100 - rank, "observed")
        for rank in (1, 2, 4)
    ]
    upsert(rows, database)

    result = _source_gate(database, stamp)
    assert result["policy_version"] == "hourly-source-proof-v2"
    assert result["passed"] is False
    assert result["sources"]["google_trends"]["row_count"] == 3
    assert result["sources"]["google_trends"]["maximum_rank"] == 4


def test_source_gate_fails_closed_for_invalid_or_inconsistent_x_evidence(tmp_path: Path):
    database = tmp_path / "runtime.sqlite3"
    stamp = "2026-08-13T17:00:00+00:00"
    x_rows = []
    for rank in range(1, 31):
        payload = {
            "collector": "codex_chrome_current_session",
            "transport": "codex_browser_snapshot",
            "profile": "current_logged_in_chrome",
            "region": "KR", "region_verified": True,
            "observed_at": "2026-08-13T17:03:00+00:00",
            "scheduled_for": stamp, "schedule_delay_seconds": 180,
        }
        if rank == 30:
            payload["schedule_delay_seconds"] = "not-a-number"
        x_rows.append(HourlyObservation(
            stamp, "x", f"x-{rank}", rank, 100 - rank, "observed",
            source_payload_json=json.dumps(payload),
        ))
    google_rows = [
        HourlyObservation(stamp, "google_trends", f"g-{rank}", rank, 100-rank, "observed")
        for rank in range(1, 4)
    ]
    upsert(x_rows + google_rows, database)

    result = _source_gate(database, stamp)

    assert result["passed"] is False
    evidence = result["sources"]["x"]["collection_evidence"]
    assert evidence["evidence_row_count"] == 30
    assert evidence["evidence_consistent"] is False


def test_source_gate_rejects_unapproved_collector_and_duplicate_rank(tmp_path: Path):
    database = tmp_path / "runtime.sqlite3"
    stamp = "2026-08-13T18:00:00+00:00"
    x_rows = [
        HourlyObservation(
            stamp, "x", f"x-{rank}", rank, 100 - rank, "observed",
            collector_version="unapproved_collector",
        )
        for rank in range(1, 31)
    ]
    google_rows = [
        HourlyObservation(stamp, "google_trends", "g-1a", 1, 99, "observed"),
        HourlyObservation(stamp, "google_trends", "g-1b", 1, 98, "observed"),
        HourlyObservation(stamp, "google_trends", "g-3", 3, 97, "observed"),
    ]
    upsert(google_rows, database)
    with connect(database) as connection:
        connection.executemany(
            "INSERT INTO hourly_observations "
            "(observed_at,source,topic,source_rank,value,provenance,collector_version) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (
                    row.observed_at, row.source, row.topic, row.source_rank,
                    row.value, row.provenance, row.collector_version,
                )
                for row in x_rows
            ],
        )
        connection.commit()

    result = _source_gate(database, stamp)
    assert result["passed"] is False
    assert "x" not in result["sources"]
    assert result["sources"]["google_trends"]["unique_ranks"] == 2
