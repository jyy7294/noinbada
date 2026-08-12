import json
from datetime import UTC, datetime

import pytest

from trzip.publication_pipeline import _collection_health, _failure_class, _validate_contract, run
from trzip.hourly_store import HourlyObservation


def test_local_cli_is_canonical_and_legacy_module_is_compatible():
    from trzip.github_pipeline import run as legacy_run
    from trzip.local_pipeline import run as local_run

    assert local_run is run
    assert legacy_run is run


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

    result = run(tmp_path)

    assert result["collection"]["observed"] == 2
    assert result["daily_file"].startswith("observations/")
    assert result["pruned_observation_files"] == 0
    intelligence = json.loads((tmp_path / "latest" / "intelligence.json").read_text(encoding="utf-8"))
    assert intelligence["mode"] == "live"
    assert intelligence["unified_ranking"][0]["display_name"] == "말복"
    assert intelligence["market_data_status"]["provider"] == "pykrx"
    assert intelligence["collection_status"]["partial"] is False
    assert intelligence["collection_status"]["source_status"] == {
        "x": "observed", "google_trends": "observed"
    }
    assert intelligence["unified_ranking"][0]["companies"][0]["market_reference"]["status"] == "observed"
    assert list((tmp_path / "observations").glob("*.json"))
    status = json.loads((tmp_path / "latest" / "status.json").read_text(encoding="utf-8"))
    assert status["partial"] is False
    assert result["storage"] == "local-sqlite-published-to-live-data"
    assert intelligence["publication_id"] == status["publication_id"] == result["publication_id"]
    assert intelligence["generated_at"] == status["generated_at"] == result["generated_at"]
    assert intelligence["window"]["to"] == status["observed_at"] == result["observed_at"]

    second = run(tmp_path)
    daily = json.loads((tmp_path / second["daily_file"]).read_text(encoding="utf-8"))
    assert len(daily) == 2
    assert second["coverage"]["rows"] == 2
    assert second["publication_id"] != result["publication_id"]


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
        "collection": {"trends_mcp_used": False, "generated": False},
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
    assert first["status"] == second["status"] == "collecting_baseline"
    assert second["source_failure_counts"]["x"]["api_authentication"] == 1
    assert second["remaining_runs_for_3d"] == 71
    assert second["source_targets_met"] == {"x": False, "google_trends": False}


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
    result = run(tmp_path / "publication", database_path=database, now=at)

    assert result["collection"]["errors"] == {}
    assert result["collection"]["audit"]["x_korea_realtime"]["status"] == "observed"
    assert "dedicated profile" in result["collection"]["audit"]["x_korea_realtime"]["detail"]
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
