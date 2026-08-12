import json
from datetime import UTC, datetime

from trzip.github_pipeline import _collection_health, _failure_class, run
from trzip.hourly_store import HourlyObservation


def test_pipeline_writes_frontend_contract(tmp_path, monkeypatch):
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    stamp = at.isoformat()

    monkeypatch.setattr("trzip.github_pipeline.floor_hour", lambda value: at)
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [HourlyObservation(stamp, "x", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.github_pipeline.pykrx_stock",
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
    assert intelligence["unified_ranking"][0]["companies"][0]["market_reference"]["status"] == "observed"
    assert list((tmp_path / "observations").glob("*.json"))

    second = run(tmp_path)
    daily = json.loads((tmp_path / second["daily_file"]).read_text(encoding="utf-8"))
    assert len(daily) == 2
    assert second["coverage"]["rows"] == 2


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


def test_failure_class_has_required_operational_buckets():
    assert _failure_class("429 quota exceeded") == "quota_or_rate_limit"
    assert _failure_class("TimeoutError") == "network"
    assert _failure_class("XML parser failed") == "parser_change"
