from datetime import UTC, datetime

from trzip.hourly_store import HourlyObservation, upsert
from trzip.intelligence import build_intelligence


def test_source_label_and_interpretation_are_separate(tmp_path):
    target = tmp_path / "display.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([
        HourlyObservation(at.isoformat(), "google_trends", "말복", 1, 100, "observed"),
        HourlyObservation(at.isoformat(), "x", "삼계탕", 2, 99, "observed"),
    ], target)
    trend = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]
    assert trend["display_name"] == "말복"
    assert set(trend["raw_terms"]) == {"말복", "삼계탕"}
    assert "보양식" in trend["phenomenon_summary"]
    assert trend["display_name"] != trend["phenomenon_summary"]


def test_unknown_cause_is_not_fabricated(tmp_path):
    target = tmp_path / "unknown.sqlite3"
    at = datetime(2026, 8, 12, 3, tzinfo=UTC)
    upsert([HourlyObservation(at.isoformat(), "x", "새로운 표현", 1, 100, "observed")], target)
    trend = build_intelligence(at, hours=1, path=target)["unified_ranking"][0]
    assert trend["display_name"] == "새로운 표현"
    assert trend["phenomenon_summary"].startswith("원인 미확인")
