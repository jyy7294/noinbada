import json
from datetime import UTC, datetime, timedelta

import pytest

from trzip.publication_pipeline import (
    _collection_health,
    _failure_class,
    _public_market_reference,
    _verification_references,
    _hourly_verification_term_limit,
    _prune_observations,
    _refresh_verification_layer,
    _sanitize_collection_for_public,
    _validate_contract,
    run,
)
from trzip.hourly_store import HourlyObservation


def test_local_cli_is_canonical():
    from trzip.local_pipeline import run as local_run

    assert local_run is run


def test_pipeline_writes_frontend_contract(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()

    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [HourlyObservation(stamp, "x", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda code, base_date, lookback_days=21: {
            "status": "observed",
            "provider": "pykrx",
            "stock_code": code,
            "summary": {
                "as_of": at.date().isoformat(),
                "close": 10000,
                "daily_change_pct": 1.25,
                "volume": 123456,
            },
            "daily_ohlcv": [],
        },
    )
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])

    result = run(tmp_path)

    assert result["collection"]["observed"] == 2
    assert result["daily_file"].startswith("observations/")
    assert result["pruned_observation_files"] == 0
    assert result["retention_policy"] == "indefinite"
    assert result["retention_days"] is None
    intelligence = json.loads((tmp_path / "latest" / "intelligence.json").read_text(encoding="utf-8"))
    assert intelligence["mode"] == "live"
    assert intelligence["unified_ranking"][0]["display_name"] == "말복"
    assert intelligence["market_data_status"]["provider"] == "pykrx"
    assert intelligence["collection_status"]["partial"] is False
    assert intelligence["collection_status"]["source_status"] == {
        "x": "observed", "google_trends": "observed"
    }
    trend = intelligence["unified_ranking"][0]
    assert {company["stock_code"] for company in trend["companies"]} == {
        "001680", "003680", "027740", "031440", "136480", "139480",
    }
    assert trend["company_resolution"]["publish_status"] == "published"
    assert len(trend["company_candidates"]) == 6
    assert list((tmp_path / "observations").glob("*.json"))
    status = json.loads((tmp_path / "latest" / "status.json").read_text(encoding="utf-8"))
    assert status["partial"] is False
    assert result["storage"] == "local-sqlite-published-to-live-data"
    assert intelligence["publication_id"] == status["publication_id"] == result["publication_id"]
    assert intelligence["generated_at"] == status["generated_at"] == result["generated_at"]
    assert intelligence["window"]["to"] == status["observed_at"] == result["observed_at"]
    assert result["schema_version"] == "trzip-live-data-v3"
    assert intelligence["verification_run"]["ranking_effect"] == "none"
    assert intelligence["news_discovery_queue"][0]["observed_term"] == "양즈깐루"

    second = run(tmp_path)
    daily = json.loads((tmp_path / second["daily_file"]).read_text(encoding="utf-8"))
    assert len(daily) == 2
    assert second["coverage"]["rows"] == 2
    assert second["publication_id"] != result["publication_id"]


def test_nonpositive_retention_preserves_all_published_daily_files(tmp_path):
    observations = tmp_path / "observations"
    observations.mkdir()
    old_file = observations / "2025-01-01.json"
    old_file.write_text("[]", encoding="utf-8")

    assert _prune_observations(tmp_path, datetime(2026, 8, 12, tzinfo=UTC), 0) == 0
    assert old_file.exists()


def _public_rows(count=5):
    rows = [
            {
                "rank": index,
                "event_key": f"event:{index}",
                "display_name": f"term {index}",
                "score": 100 - index,
                "lane": "main",
                "latest_source_ranks": {"google_trends": index},
            }
            for index in range(1, count + 1)
        ]
    return {
        "unified_ranking": rows,
        "public_top10": list(rows),
        "collection_status": {"partial": False, "errors": {}},
    }


def test_hourly_verification_uses_three_main_candidates_and_reuses_ledger(
    tmp_path, monkeypatch
):
    from trzip.provider_verification import (
        ProviderCredentials,
        read_verification_ledger,
        verify_terms as actual_verify_terms,
    )

    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    database = tmp_path / "runtime.sqlite3"
    intelligence = _public_rows()
    selected = _verification_references(intelligence, limit=3)
    assert [item.trend_key for item in selected] == ["event:1", "event:2", "event:3"]
    assert _hourly_verification_term_limit({"TRZIP_PROVIDER_VERIFICATION_TERM_LIMIT": "99"}) == 3

    calls = []

    def offline_verify(references, **kwargs):
        calls.append([item.trend_key for item in references])
        return actual_verify_terms(
            references,
            path=kwargs["path"],
            at=kwargs["at"],
            credentials=ProviderCredentials(),
        )

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", offline_verify)
    before = [
        (item["rank"], item["score"])
        for item in intelligence["unified_ranking"]
    ]
    first = _refresh_verification_layer(intelligence, database, at)

    assert calls == [["event:1", "event:2", "event:3"]]
    assert len(read_verification_ledger(database)) == 9
    assert first["verification_run"] == {
        "status": "completed",
        "requested_terms": 3,
        "attempted_terms": 3,
        "hourly_term_limit": 3,
        "selection_policy": "never_verified_then_oldest_verified_then_current_rank",
        "candidate_count": 5,
        "selection_scope": "current_main_candidates_including_context_review",
        "providers": ["naver", "youtube", "instagram"],
        "ranking_effect": "none",
        "affects_collection_partial": False,
        "blocks_publication": False,
        "error": None,
    }
    assert before == [
        (item["rank"], item["score"])
        for item in first["unified_ranking"]
    ]
    assert first["collection_status"]["partial"] is False

    second = _refresh_verification_layer(first, database, at)

    assert calls == [["event:1", "event:2", "event:3"]]
    assert len(read_verification_ledger(database)) == 9
    assert second["verification_run"]["status"] == "skipped_already_recorded_for_hour"
    assert second["verification_run"]["attempted_terms"] == 0


def test_hourly_verification_rotates_across_public_ten_before_rechecking_old_rows(
    tmp_path, monkeypatch
):
    from datetime import timedelta
    from trzip.provider_verification import ProviderCredentials, verify_terms as actual_verify_terms

    database = tmp_path / "runtime.sqlite3"
    intelligence = _public_rows(10)
    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    batches = []

    def offline_verify(references, **kwargs):
        batches.append([item.trend_key for item in references])
        return actual_verify_terms(
            references,
            path=kwargs["path"],
            at=kwargs["at"],
            credentials=ProviderCredentials(),
        )

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", offline_verify)
    for offset in range(4):
        _refresh_verification_layer(intelligence, database, at + timedelta(hours=offset))

    assert batches == [
        ["event:1", "event:2", "event:3"],
        ["event:4", "event:5", "event:6"],
        ["event:7", "event:8", "event:9"],
        ["event:10", "event:1", "event:2"],
    ]


def test_verification_failure_is_separate_and_never_marks_core_partial(
    tmp_path, monkeypatch
):
    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    intelligence = _public_rows(1)

    def fail_verification(*args, **kwargs):
        raise RuntimeError("provider temporarily unavailable")

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", fail_verification)
    result = _refresh_verification_layer(intelligence, tmp_path / "runtime.sqlite3", at)

    assert result["verification_run"]["status"] == "failed_non_blocking"
    assert result["verification_run"]["error"] == "provider_verification_failed"
    assert result["verification_run"]["blocks_publication"] is False
    assert result["verification_run"]["affects_collection_partial"] is False
    assert result["collection_status"]["partial"] is False


def test_provider_verification_uses_unified_main_candidates_but_skips_issue_lane():
    hidden = {
        "rank": 1,
        "event_key": "hidden-issue",
        "display_name": "hidden issue",
        "latest_source_ranks": {"google_trends": 1},
        "lane": "issue",
    }
    visible = {
        "rank": 9,
        "event_key": "visible-main",
        "display_name": "visible main",
        "latest_source_ranks": {"google_trends": 9},
        "lane": "main",
    }
    selected = _verification_references(
        {"unified_ranking": [hidden, visible], "public_top10": [visible]},
        limit=3,
    )
    assert [item.trend_key for item in selected] == ["visible-main"]


def test_market_reference_public_contract_removes_provider_exception_text():
    sanitized = _public_market_reference(
        {
            "status": "error",
            "stock_code": "005930",
            "reason": "RuntimeError: C:\\Users\\name\\secret.txt?token=abc",
        },
        "005930",
    )
    assert sanitized == {
        "status": "error",
        "stock_code": "005930",
        "reason": "market_reference_error",
    }


def test_scheduled_publication_appends_only_three_gold_terms_once_per_hour(
    tmp_path, monkeypatch
):
    from trzip.provider_verification import (
        ProviderCredentials,
        read_verification_ledger,
        verify_terms as actual_verify_terms,
    )

    at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    stamp = at.isoformat()
    database = tmp_path / "runtime.sqlite3"
    topics = ["업비트", "네이마르", "지드래곤", "말복"]
    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [
            HourlyObservation(stamp, "google_trends", topic, index, 101 - index, "observed")
            for index, topic in enumerate(topics, start=1)
        ],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [
            HourlyObservation(stamp, "x", topic, index, 101 - index, "observed")
            for index, topic in enumerate(topics, start=1)
        ],
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )

    def offline_verify(references, **kwargs):
        return actual_verify_terms(
            references,
            path=kwargs["path"],
            at=kwargs["at"],
            credentials=ProviderCredentials(),
        )

    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", offline_verify)
    run(tmp_path / "publication", database_path=database, now=at)
    first_payload = json.loads(
        (tmp_path / "publication" / "latest" / "intelligence.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(read_verification_ledger(database)) == 9
    assert first_payload["verification_run"]["status"] == "completed"
    assert first_payload["verification_run"]["requested_terms"] == 3
    assert first_payload["verification_run"]["ranking_effect"] == "none"

    run(tmp_path / "publication", database_path=database, now=at)
    second_payload = json.loads(
        (tmp_path / "publication" / "latest" / "intelligence.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(read_verification_ledger(database)) == 9
    assert second_payload["verification_run"]["status"] == "skipped_already_recorded_for_hour"


def test_news_discovery_becomes_context_only_after_core_source_observation(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()
    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [
            HourlyObservation(stamp, "google_trends", "양즈깐루", 1, 100, "observed")
        ],
    )
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: [])
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )

    run(tmp_path)

    intelligence = json.loads(
        (tmp_path / "latest" / "intelligence.json").read_text(encoding="utf-8")
    )
    trend = intelligence["unified_ranking"][0]
    news = next(
        item for item in intelligence["news_discovery_queue"]
        if item["observed_term"] == "양즈깐루"
    )
    assert news["core_source_gate"] == "satisfied_by_x_or_google"
    assert news["ranking_insertion_performed"] is False
    assert trend["news_context"]["status"] == "observed"
    assert trend["news_context"]["claim_types"] == ["consumer_behavior"]
    assert trend["news_context"]["affects_score"] is False


@pytest.mark.parametrize(
    ("changed_document", "field", "value", "message"),
    [
        ("status", "publication_id", "pub-other", "publication_id"),
        ("metadata", "generated_at", "2026-08-12T03:00:01+00:00", "generated_at"),
        ("status", "observed_at", "2026-08-12T04:00:00+00:00", "observation window"),
    ],
)
def test_publication_contract_rejects_mixed_document_bundle(
    changed_document, field, value, message
):
    observed_at = "2026-08-12T03:00:00+00:00"
    generated_at = "2026-08-12T03:00:05+00:00"
    intelligence = {
        "mode": "live",
        "publication_id": "pub-one",
        "generated_at": generated_at,
        "window": {"to": observed_at},
        "unified_ranking": [],
    }
    metadata = {
        "mode": "live",
        "publication_id": "pub-one",
        "generated_at": generated_at,
        "observed_at": observed_at,
        "collection": {"rank_sources": ["x", "google_trends"]},
    }
    status = {
        "mode": "live",
        "publication_id": "pub-one",
        "generated_at": generated_at,
        "observed_at": observed_at,
    }
    {"intelligence": intelligence, "metadata": metadata, "status": status}[
        changed_document
    ][field] = value

    with pytest.raises(ValueError, match=message):
        _validate_contract(intelligence, metadata, status)


def test_collection_health_deduplicates_hour_and_classifies_source_failures(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    collection = {
        "observed": 10,
        "errors": {"x": "HTTP Error 401: Unauthorized"},
        "audit": {
            "x_korea_realtime": {"status": "unavailable", "detail": "token rejected"},
            "google_geo_kr": {"status": "observed", "detail": "geo=KR"},
        },
    }
    first = _collection_health(tmp_path, at, collection, at, at)
    second = _collection_health(tmp_path, at, collection, at, at)
    history = json.loads((tmp_path / "monitoring" / "run_history.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    assert history[0]["contract_version"] == "trzip-v3-hourly"
    assert first["status"] == second["status"] == "collecting_baseline"
    assert second["source_failure_counts"]["x"]["api_authentication"] == 1
    assert second["remaining_runs_for_3d"] == 71
    assert second["source_targets_met"] == {"x": False, "google_trends": False}


def test_collection_health_preserves_first_scheduler_timing_on_manual_retry(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    collection = {
        "observed": 100,
        "errors": {"x": "extension_not_ready"},
        "audit": {
            "x_korea_realtime": {"status": "extension_not_ready", "row_count": 0},
            "google_geo_kr": {"status": "observed", "row_count": 100},
        },
    }
    first = _collection_health(
        tmp_path, at, collection, at + timedelta(seconds=2), at + timedelta(seconds=10)
    )
    second = _collection_health(
        tmp_path, at, collection, at + timedelta(minutes=20), at + timedelta(minutes=21)
    )

    assert first["latest_delay_seconds"] == second["latest_delay_seconds"] == 2
    assert second["recorded_runs"] == 1


def test_collection_health_drops_unversioned_legacy_success_rows(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    monitoring = tmp_path / "monitoring"
    monitoring.mkdir()
    (monitoring / "run_history.json").write_text(
        json.dumps([{
            "scheduled_at": "2026-08-12T02:00:00+00:00",
            "success": True,
            "source_success": {"x": True, "google_trends": True},
        }]),
        encoding="utf-8",
    )
    collection = {
        "observed": 193,
        "errors": {"x": "extension_not_ready"},
        "audit": {
            "x_korea_realtime": {"status": "extension_not_ready", "row_count": 0},
            "google_geo_kr": {"status": "observed", "row_count": 193},
        },
    }

    health = _collection_health(tmp_path, at, collection, at, at)

    assert health["recorded_runs"] == 1
    assert health["successful_runs"] == 0
    assert health["source_success_rate"] == {"x": 0.0, "google_trends": 1.0}


def test_public_collection_and_monitoring_redact_local_paths_urls_and_credentials(tmp_path):
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    secret_detail = (
        r"XCollectionError: extension_not_ready: X inbox does not exist: "
        r"C:\\Users\\person\\Desktop\\TRZIP\\x.json?token=super-secret"
    )
    collection = {
        "observed": 185,
        "observed_at": at.isoformat(),
        "rank_sources": ["x", "google_trends"],
        "errors": {"x": secret_detail},
        "audit": {
            "x_korea_realtime": {
                "status": "extension_not_ready",
                "row_count": 0,
                "detail": secret_detail,
            },
            "google_geo_kr": {
                "status": "observed",
                "row_count": 185,
                "declared_total": 185,
                "page_count": 8,
                "completion_verified": True,
                "detail": "https://trends.google.com/trending?geo=KR&key=super-secret",
            },
        },
    }

    public = _sanitize_collection_for_public(collection)
    monitoring = tmp_path / "monitoring"
    monitoring.mkdir()
    (monitoring / "run_history.json").write_text(
        json.dumps([
            {
                "scheduled_at": "2026-08-12T02:00:00+00:00",
                "started_at": "2026-08-12T02:00:00+00:00",
                "finished_at": "2026-08-12T02:00:01+00:00",
                "delay_seconds": 0,
                "duration_seconds": 1,
                "success": False,
                "source_success": {"x": False, "google_trends": True},
                "observed_rows": 185,
                "errors": {"x": secret_detail},
                "source_failures": {
                    "x": {"class": "unknown", "detail": secret_detail}
                },
            }
        ]),
        encoding="utf-8",
    )
    health = _collection_health(tmp_path, at, collection, at, at)
    run_history = (tmp_path / "monitoring" / "run_history.json").read_text(encoding="utf-8")
    latest = (tmp_path / "monitoring" / "latest.json").read_text(encoding="utf-8")
    serialized = json.dumps({"collection": public, "health": health}) + run_history + latest

    assert public["errors"] == {"x": "extension_not_ready"}
    assert public["audit"]["x_korea_realtime"]["detail"] == "extension_not_ready"
    assert public["audit"]["google_geo_kr"]["detail"] == "verified_current_hour_snapshot"
    assert public["audit"]["google_geo_kr"]["declared_total"] == 185
    assert public["audit"]["google_geo_kr"]["page_count"] == 8
    assert public["audit"]["google_geo_kr"]["completion_verified"] is True
    assert "C:\\Users" not in serialized
    assert "https://" not in serialized
    assert "super-secret" not in serialized
    assert "token=" not in serialized


def test_pipeline_uses_preserved_same_hour_source_after_retry_failure(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()
    database = tmp_path / "runtime.sqlite3"
    from trzip.hourly_store import collect_current

    monkeypatch.setattr("trzip.publication_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [HourlyObservation(stamp, "x", "불꽃축제", 1, 100, "observed")],
    )
    collect_current(database, at)

    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: (_ for _ in ()).throw(RuntimeError("browser temporarily unavailable")),
    )
    monkeypatch.setattr(
        "trzip.publication_pipeline.pykrx_stock",
        lambda *args, **kwargs: {"status": "unavailable", "reason": "test"},
    )
    monkeypatch.setattr("trzip.publication_pipeline.verify_terms", lambda *args, **kwargs: [])
    result = run(tmp_path / "publication", database_path=database, now=at)

    assert result["collection"]["errors"] == {}
    assert result["collection"]["audit"]["x_korea_realtime"]["status"] == "observed"
    assert result["collection"]["audit"]["x_korea_realtime"]["detail"] == "verified_current_hour_snapshot"
    assert result["collection"]["observed"] == 2
    status = json.loads(
        (tmp_path / "publication" / "latest" / "status.json").read_text(encoding="utf-8")
    )
    assert status["partial"] is False


def test_failure_class_has_required_operational_buckets():
    assert _failure_class("429 quota exceeded") == "quota_or_rate_limit"
    assert _failure_class("TimeoutError") == "network"
    assert _failure_class("XML parser failed") == "parser_change"
    assert _failure_class("auth_required: login once") == "browser_authentication"
    assert _failure_class("region_unverified") == "region_configuration"
    assert _failure_class("selector_changed") == "browser_page_change"
