from pathlib import Path
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

from trzip.hourly_store import HourlyObservation, connect, upsert
from trzip.result_quality import (
    _hourly_validation_receipt,
    _source_gate,
    evaluate_actual_hour,
    evaluate_consecutive_hours,
    evaluate_frontend_result,
    evaluate_local_consecutive_hours,
    hourly_validation_receipt_exists,
    main as result_quality_main,
    publication_receipt_exists,
    record_hourly_validation_receipt,
    record_publication_receipt,
    register_hourly_trigger,
)
from trzip.presentation_feed import (
    LOGO_ASSET_VERIFICATION,
    LOGO_MINIMUM_DIMENSION,
    LOGO_QUALITY_POLICY,
    build_presentation_feed,
)


def _company(index: int) -> dict:
    if index <= 4:
        role_category, role_label, stage = "manufacturing_development", "제조·개발", "core"
    elif index <= 7:
        role_category, role_label, stage = "distribution", "배급·유통", "downstream"
    else:
        role_category, role_label, stage = "platform_service", "플랫폼·서비스", "service"
    return {
        "company": f"기업{index}",
        "stock_code": f"00000{index}",
        "market": "KRX",
        "company_description": "설명",
        "relationship_reason": "관계 이유",
        "connection_explanation": "키워드 0과 기업의 확인된 역할을 설명합니다.",
        "company_role_category": role_category,
        "company_role_label": role_label,
        "value_chain_stage": stage,
        "ontology_complete": True,
        "ontology_path": [
            {"from": "event", "to": "industry"},
            {"from": "industry", "to": f"기업{index}"},
        ],
        "relation_tier": "direct",
        "evidence_sources": [{"url": f"https://example.com/{index}"}],
        "official_domain": "example.com",
        "logo_url": (
            "https://www.google.com/s2/favicons?sz=128&domain_url="
            "https%3A%2F%2Fexample.com"
        ),
        "logo_asset_source": "official_domain_declared_favicon",
        "logo_asset_host": "www.google.com",
        "logo_asset_verification": LOGO_ASSET_VERIFICATION,
        "logo_quality_policy": LOGO_QUALITY_POLICY,
        "logo_render_mode": "runtime_probe",
        "logo_asset_format": "remote_declared_icon",
        "logo_asset_width": 0,
        "logo_asset_height": 0,
        "logo_minimum_dimension": LOGO_MINIMUM_DIMENSION,
        "logo_runtime_probe_required": True,
        "logo_asset_quality": "unverified_dimensions_runtime_gate",
        "logo_rejected_asset_url": "",
        "market_snapshot": {
            "last_price": 10000 + index,
            "change_percent": 1.2,
            "per": 12.0,
            "pbr": 1.3,
            "roe_percent": 10.0,
            "price_series": [10000 + index + point for point in range(30)],
            "display_only": True,
            "ranking_effect": "none",
        },
    }


def _trend(rank: int) -> dict:
    return {
        "publication_rank": rank,
        "event_key": f"event:{rank}",
        "display_name": f"트렌드 {rank}",
        "selection_origin": "reviewed_observed_reference_test",
        "observed_rank": rank * 2,
        "broad_category": "technology",
        "trend_definition": (
            "구체적인 기술 대상이 최근 관심을 받은 트렌드입니다. "
            "X와 Google 대한민국 관측값에서 발생 맥락과 연결 산업이 함께 확인됐습니다."
        ),
        "disclaimer": "투자 추천이나 수익 예측이 아닙니다.",
        "frontend_readiness_status": "ready",
        "context_research": {
            "status": "ready",
            "trigger_title": "공식 발표로 관심이 증가",
            "why_now": "공식 발표 직후 X와 Google 대한민국에서 관심이 상승했습니다.",
            "trigger_type": "official_announcement",
            "published_at": "2026-08-13T00:00:00+00:00",
            "evidence_urls": [f"https://example.com/context/{rank}"],
            "evidence_records": [],
            "affects_score": False,
            "ranking_source": False,
        },
        "company_card_status": "ready",
        "company_card_reason": "evidence_backed_ten_or_more",
        "related_keywords": [
            {"text": f"키워드 {index}", "source": ["google_trends"]}
            for index in range(5)
        ],
        "companies": [_company(index) for index in range(1, 11)],
        "visualization_series": {
            "display_only": True,
            "ranking_effect": "none",
            "canonical_series_unchanged": True,
            **{
                key: {
                    "labels": [str(index) for index in range(size)],
                    "x": [50.0] * size,
                    "google_trends": [55.0] * size,
                    "combined": [52.5] * size,
                }
                for key, size in (("1w", 7), ("1m", 30), ("3m", 13))
            },
        },
        "keyword_company_links": [
            {
                "keyword": f"키워드 {index}",
                "company": f"기업{index + 1}",
                "connection_explanation": "키워드와 기업의 확인된 역할 연결입니다.",
                "evidence_urls": [f"https://example.com/{index + 1}"],
            }
            for index in range(2)
        ],
    }


def test_complete_frontend_result_passes_quality_gate():
    result = evaluate_frontend_result({"home_top10": [_trend(rank) for rank in range(1, 11)]})

    assert result["passed"] is True
    assert result["policy_version"] == "frontend-result-quality-v7"
    assert result["trend_count"] == 10
    assert all(row["keyword_count"] == 5 and row["company_count"] == 10 for row in result["trends"])


def test_presentation_feed_is_counted_as_the_actual_frontend_surface():
    intelligence = {
        "home_feed": {"status": "empty", "groups": []},
        "home_top10": [],
        "presentation_feed": build_presentation_feed({"unified_ranking": []}),
    }

    result = evaluate_frontend_result(intelligence)

    assert result["policy_version"] == "frontend-result-quality-v8"
    assert result["passed"] is True
    assert result["frontend_surface"] == "presentation_feed"
    assert result["canonical_home_count"] == 0
    assert result["canonical_home_content_ready"] is False
    assert result["home_count"] == 10
    assert result["trend_count"] == 10
    assert result["company_ready_count"] == 10
    assert result["presentation_count"] == 10
    assert result["presentation_content_ready"] is True
    assert result["home_content_ready"] is True


def test_presentation_quality_rejects_a_missing_logo_without_hiding_canonical_state():
    feed = build_presentation_feed({"unified_ranking": []})
    feed["items"][0]["companies"][0].pop("logo_url")
    result = evaluate_frontend_result({
        "home_feed": {"status": "empty", "groups": []},
        "presentation_feed": feed,
    })

    assert result["passed"] is False
    assert result["canonical_home_count"] == 0
    assert result["presentation_count"] == 10
    assert result["company_ready_count"] == 9
    assert result["presentation_content_ready"] is False
    assert any("missing_official_logo" in failure for failure in result["failures"])


def test_presentation_quality_accepts_initials_for_reviewed_low_resolution_logo():
    feed = build_presentation_feed({"unified_ranking": []})
    initials_company = next(
        company
        for item in feed["items"]
        for company in item["companies"]
        if company.get("logo_render_mode") == "initials"
    )

    result = evaluate_frontend_result({
        "home_feed": {"status": "empty", "groups": []},
        "presentation_feed": feed,
    })

    assert initials_company["logo_url"] == ""
    assert initials_company["logo_rejected_asset_url"].startswith("https://")
    assert result["passed"] is True


def test_presentation_quality_rejects_missing_blur_safe_logo_policy():
    feed = build_presentation_feed({"unified_ranking": []})
    feed["items"][0]["companies"][0].pop("logo_quality_policy")

    result = evaluate_frontend_result({
        "home_feed": {"status": "empty", "groups": []},
        "presentation_feed": feed,
    })

    assert result["passed"] is False
    assert any("invalid_v3_logo_metadata" in failure for failure in result["failures"])


def test_home_selection_rejects_pending_keyword_and_company_enrichment():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["related_keywords"] = trends[0]["related_keywords"][:2]
    trends[0]["companies"] = trends[0]["companies"][:3]
    trends[0]["frontend_readiness_status"] = "enrichment_pending"
    trends[0]["company_card_status"] = "enrichment_pending"
    trends[0]["company_card_reason"] = "fewer_than_ten_evidence_backed_companies"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("keyword_count:2" in failure for failure in result["failures"])
    assert any("company_count:3" in failure for failure in result["failures"])
    assert any("frontend_enrichment_pending" in failure for failure in result["failures"])


def test_quality_gate_rejects_company_state_mismatch_and_expired_rising():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["company_card_status"] = "enrichment_pending"
    trends[0]["company_card_reason"] = "fewer_than_ten_evidence_backed_companies"
    expired = {
        "event_key": "expired-event",
        "display_name": "Expired event",
        "is_current": False,
        "lifecycle": "expired",
    }

    result = evaluate_frontend_result({"home_top10": trends, "rising_top10": [expired]})

    assert result["passed"] is False
    assert any("company_card_not_ready" in failure for failure in result["failures"])
    assert any("company_card_reason_mismatch" in failure for failure in result["failures"])
    assert "Expired event:non_current_rising_trend" in result["failures"]


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


def test_quality_gate_rejects_invalid_relation_url_and_ontology_destination():
    trends = [_trend(rank) for rank in range(1, 11)]
    company = trends[0]["companies"][0]
    company["relation_tier"] = "sponsor_guess"
    company["evidence_sources"] = [{"url": "not-a-public-url"}]
    company["ontology_path"][-1]["to"] = "다른 기업"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("invalid_relation_tier" in failure for failure in result["failures"])
    assert any("invalid_company_evidence_url" in failure for failure in result["failures"])
    assert any("ontology_path_not_to_company" in failure for failure in result["failures"])


def test_quality_gate_rejects_missing_logo_market_snapshot_and_display_series():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["companies"][0].pop("logo_url")
    trends[0]["companies"][1].pop("market_snapshot")
    trends[0]["visualization_series"]["1w"]["x"].pop()

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("missing_official_logo" in failure for failure in result["failures"])
    assert any("market_snapshot_incomplete" in failure for failure in result["failures"])
    assert any("visualization_series_incomplete:1w" in failure for failure in result["failures"])


def test_quality_gate_allows_multiple_evidence_complete_food_trends():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["broad_category"] = "food"
    trends[1]["broad_category"] = "food"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is True


def test_quality_gate_rejects_duplicate_keyword_and_missing_context():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["related_keywords"][1]["text"] = trends[0]["related_keywords"][0]["text"]
    trends[0]["trend_definition"] = ""
    trends[1]["broad_category"] = "other"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any("empty_or_duplicate_keyword" in failure for failure in result["failures"])
    assert any("missing_trend_definition" in failure for failure in result["failures"])
    assert any("invalid_category" in failure for failure in result["failures"])


def test_quality_gate_rejects_keyword_over_six_non_whitespace_characters():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["related_keywords"][0]["text"] = "일곱글자키워드"

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert any(
        "keyword_exceeds_six_characters" in failure
        for failure in result["failures"]
    )


def test_quality_gate_rejects_shallow_or_unbounded_trend_definition():
    trends = [_trend(rank) for rank in range(1, 11)]
    trends[0]["trend_definition"] = "최근 관측된 기술 트렌드입니다."
    trends[1]["trend_definition"] = (
        "구체적인 기술 대상이 최근 관심을 받은 트렌드입니다. "
        "X와 Google 대한민국 관측값을 바탕으로 발생 맥락을 설명하며 투자 조언이 아닙니다."
    )

    result = evaluate_frontend_result({"home_top10": trends})

    assert result["passed"] is False
    assert sum("insufficient_trend_definition" in failure for failure in result["failures"]) == 2


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


def _write_complete_source_hour(database: Path, at: datetime) -> None:
    stamp = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
    actual = (datetime.fromisoformat(stamp) + timedelta(minutes=3)).isoformat()
    x_evidence = json.dumps({
        "collector": "codex_chrome_current_session",
        "transport": "codex_browser_snapshot",
        "profile": "current_logged_in_chrome",
        "region": "KR",
        "region_verified": True,
        "observed_at": actual,
        "scheduled_for": stamp,
        "schedule_delay_seconds": 180,
    })
    rows = [
        HourlyObservation(
            stamp,
            "x",
            f"x-{stamp}-{rank}",
            rank,
            100 - rank,
            "observed",
            source_payload_json=x_evidence,
            collector_version="x_current_session_kr_v1",
        )
        for rank in range(1, 31)
    ] + [
        HourlyObservation(
            stamp,
            "google_trends",
            f"g-{stamp}-{rank}",
            rank,
            100 - rank,
            "observed",
            collector_version="google_trending_now_kr_v1",
        )
        for rank in range(1, 4)
    ]
    upsert(rows, database)


def test_eight_hour_local_streak_requires_only_daily_end_publication(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    end = datetime(2026, 8, 14, 21, tzinfo=UTC)
    for offset in reversed(range(8)):
        hour = end - timedelta(hours=offset)
        _write_complete_source_hour(database, hour)

    without_receipts = evaluate_local_consecutive_hours(database, end=end, count=8)
    assert without_receipts["passed"] is False
    assert without_receipts["current_consecutive_success_count"] == 0

    contract = evaluate_frontend_result({"home_feed": {"status": "empty", "groups": []}})
    for offset in reversed(range(8)):
        hour = end - timedelta(hours=offset)
        stamp = hour.astimezone(UTC).replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
        record_hourly_validation_receipt(
            database,
            observed_at=stamp,
            publication_id=f"pub-{stamp}",
            frontend_manifest_sha256="a" * 64,
            contract=contract,
            source_gate=_source_gate(database, stamp),
        )

    local = evaluate_local_consecutive_hours(database, end=end, count=8)
    before_publication = evaluate_consecutive_hours(database, end=end, count=8)

    assert local["passed"] is True
    assert local["current_consecutive_success_count"] == 8
    assert local["content_ready_hour_count"] == 0
    assert before_publication["passed"] is False
    assert before_publication["daily_publication_verified"] is False

    last = local["evaluations"][-1]
    record_publication_receipt(
        database,
        observed_at=end.isoformat(),
        publication_id="pub-" + ("d" * 32),
        remote_sha="a" * 40,
        contract=last["contract"],
        source_gate=last["source_gate"],
        manifest_sha256="b" * 64,
        remote_manifest_blob="c" * 40,
    )

    after_publication = evaluate_consecutive_hours(database, end=end, count=8)

    assert after_publication["policy_version"] == "consecutive-actual-result-v4"
    assert after_publication["passed"] is True
    assert after_publication["daily_publication_verified"] is True
    assert after_publication["presentation_ready"] is False


def test_hourly_validation_receipt_is_idempotent_immutable_and_source_bound(
    tmp_path: Path,
) -> None:
    database = tmp_path / "hourly-receipt.sqlite3"
    at = datetime(2026, 8, 15, 1, tzinfo=UTC)
    stamp = at.isoformat()
    _write_complete_source_hour(database, at)
    source_gate = _source_gate(database, stamp)
    contract = evaluate_frontend_result({"home_feed": {"status": "empty", "groups": []}})

    first = record_hourly_validation_receipt(
        database, observed_at=stamp, publication_id="pub-hourly-receipt",
        frontend_manifest_sha256="b" * 64, contract=contract,
        source_gate=source_gate,
    )
    second = record_hourly_validation_receipt(
        database, observed_at=stamp, publication_id="pub-hourly-receipt",
        frontend_manifest_sha256="b" * 64, contract=contract,
        source_gate=source_gate,
    )

    assert first["passed"] is True
    assert second["receipt_sha256"] == first["receipt_sha256"]
    assert hourly_validation_receipt_exists(database, stamp) is True
    assert publication_receipt_exists(database, stamp) is False
    with pytest.raises(ValueError, match="frontend contract did not pass"):
        record_hourly_validation_receipt(
            database,
            observed_at=stamp,
            publication_id="pub-hourly-receipt",
            frontend_manifest_sha256="b" * 64,
            contract={**contract, "policy_version": "frontend-result-quality-v6"},
            source_gate=source_gate,
        )
    with pytest.raises(ValueError, match="immutable hourly validation receipt"):
        record_hourly_validation_receipt(
            database,
            observed_at=stamp,
            publication_id="pub-hourly-receipt",
            frontend_manifest_sha256="c" * 64,
            contract=contract,
            source_gate=source_gate,
        )
    with pytest.raises(ValueError, match="immutable hourly validation receipt"):
        record_hourly_validation_receipt(
            database,
            observed_at=stamp,
            publication_id="pub-hourly-receipt",
            frontend_manifest_sha256="b" * 64,
            contract={**contract, "home_content_ready": True},
            source_gate=source_gate,
        )

    with connect(database) as connection:
        connection.execute(
            "UPDATE hourly_observations SET topic='mutated' "
            "WHERE observed_at=? AND source='google_trends' AND source_rank=1",
            (stamp,),
        )

    tampered = _hourly_validation_receipt(database, stamp)
    assert tampered["passed"] is False
    assert "source_snapshot_digest_mismatch" in tampered["failures"]


def test_hourly_validation_cli_is_safe_to_repeat_and_manifest_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "hourly-cli.sqlite3"
    at = datetime(2026, 8, 15, 2, tzinfo=UTC)
    stamp = at.isoformat()
    _write_complete_source_hour(database, at)
    publication_id = "pub-hourly-cli"
    intelligence_path = tmp_path / "intelligence.json"
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "result_quality.json"
    intelligence_path.write_text(
        json.dumps({
            "publication_id": publication_id,
            "home_feed": {"status": "empty", "groups": []},
        }),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps({"publication_id": publication_id, "observed_at": stamp}),
        encoding="utf-8",
    )
    arguments = [
        "trzip.result_quality",
        "--database", str(database),
        "--end", stamp,
        "--record-hourly-validation",
        "--intelligence", str(intelligence_path),
        "--manifest", str(manifest_path),
        "--count", "1",
        "--output", str(output_path),
    ]

    monkeypatch.setattr(sys, "argv", arguments)
    assert result_quality_main() == 0
    first_receipt = _hourly_validation_receipt(database, stamp)
    monkeypatch.setattr(sys, "argv", arguments)
    assert result_quality_main() == 0

    assert _hourly_validation_receipt(database, stamp)["receipt_sha256"] == (
        first_receipt["receipt_sha256"]
    )
    assert json.loads(output_path.read_text(encoding="utf-8"))[
        "local_hourly_validation"
    ]["current_consecutive_success_count"] == 1

    manifest_path.write_text(
        json.dumps({
            "publication_id": publication_id,
            "observed_at": (at + timedelta(hours=1)).isoformat(),
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as failure:
        result_quality_main()
    assert failure.value.code == 2


def test_trigger_registration_records_only_true_missed_hours(tmp_path: Path) -> None:
    database = tmp_path / "trigger-gaps.sqlite3"
    first = datetime(2026, 8, 15, 1, tzinfo=UTC)

    assert register_hourly_trigger(database, first)["missed_hours"] == []
    assert register_hourly_trigger(database, first)["missed_hours"] == []
    third = register_hourly_trigger(database, first + timedelta(hours=3))

    assert third["missed_hours"] == [
        "2026-08-15T02:00:00+00:00",
        "2026-08-15T03:00:00+00:00",
    ]
    missed = evaluate_actual_hour(database, first + timedelta(hours=1))
    assert missed["local_passed"] is False
    assert missed["missed_trigger"]["reason"] == "missed_trigger"
    missed_hour = first + timedelta(hours=1)
    missed_stamp = missed_hour.isoformat()
    _write_complete_source_hour(database, missed_hour)
    with pytest.raises(ValueError, match="recorded as a missed trigger"):
        record_hourly_validation_receipt(
            database,
            observed_at=missed_stamp,
            publication_id="pub-retroactive-gap",
            frontend_manifest_sha256="d" * 64,
            contract=evaluate_frontend_result({
                "home_feed": {"status": "empty", "groups": []},
            }),
            source_gate=_source_gate(database, missed_stamp),
        )
    with pytest.raises(ValueError, match="precedes the last registered trigger"):
        register_hourly_trigger(database, first + timedelta(hours=2))
