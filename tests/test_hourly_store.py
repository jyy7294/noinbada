import json
from datetime import UTC, date, datetime, timedelta

import pytest

from trzip.hourly_store import (
    HourlyObservation,
    collect_current,
    collect_google,
    connect,
    coverage,
    daily_aggregates,
    hourly_rankings,
    latest_audit,
    snapshot,
    source_hour_quality,
    store_verified_source_snapshot,
    upsert,
)


def test_production_ledger_rejects_generated_rows(tmp_path):
    target = tmp_path / "observed-only.sqlite3"
    at = datetime(2026, 8, 12, 2, tzinfo=UTC)
    stamp = at.isoformat()
    with pytest.raises(ValueError, match="observed rows only"):
        upsert([
            HourlyObservation(stamp, "google_trends", "말복", 1, 100, "generated"),
        ], target)


def test_scheduled_collection_has_no_trends_mcp_path(tmp_path, monkeypatch):
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    monkeypatch.setenv("TRENDS_MCP_API_KEY", "configured-but-disabled")
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: [])

    result = collect_current(tmp_path / "hourly.sqlite3", at)

    assert result["rank_sources"] == ["x", "google_trends"]
    assert "trends_mcp_used" not in result
    assert "generated" not in result
    assert "google_trends_mcp" not in result["audit"]
    assert "web full-list" in result["audit"]["google_geo_kr"]["detail"]
    assert "RSS" not in result["audit"]["google_geo_kr"]["detail"]


def test_trends_mcp_collector_symbol_is_removed():
    import trzip.hourly_store as hourly_store

    assert not hasattr(hourly_store, "collect_trends_mcp")


def test_failed_source_does_not_erase_successful_snapshot_for_same_hour(tmp_path, monkeypatch):
    target = tmp_path / "preserve.sqlite3"
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: [HourlyObservation(stamp, "x", "불꽃축제", 1, 100, "observed")],
    )
    collect_current(target, at)

    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "삼성전자", 1, 100, "observed")],
    )
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: (_ for _ in ()).throw(RuntimeError("offline")))
    result = collect_current(target, at)
    rows = snapshot(at, target)

    assert result["errors"]["x"].startswith("RuntimeError")
    assert {row["topic"] for row in rows if row["source"] == "x"} == {"불꽃축제"}
    assert {row["topic"] for row in rows if row["source"] == "google_trends"} == {"삼성전자"}


def test_first_complete_same_hour_snapshots_are_not_rewritten(tmp_path, monkeypatch):
    target = tmp_path / "first-snapshot.sqlite3"
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    google_payload = json.dumps({
        "collection_declared_total": 100,
        "collection_page_count": 4,
        "collection_completion_verified": True,
    })
    first_google = [
        HourlyObservation(
            stamp, "google_trends", f"첫구글{rank}", rank, 100, "observed",
            source_payload_json=google_payload,
            collector_version="google_trending_now_kr_v1",
        )
        for rank in range(1, 101)
    ]
    first_x = [
        HourlyObservation(
            stamp, "x", f"첫X{rank}", rank, 100, "observed",
            collector_version="x_current_session_kr_v1",
        )
        for rank in range(1, 31)
    ]
    monkeypatch.setattr("trzip.hourly_store.collect_google", lambda value: first_google)
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: first_x)
    first = collect_current(target, at)

    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: (_ for _ in ()).throw(AssertionError("must reuse Google")),
    )
    monkeypatch.setattr(
        "trzip.hourly_store.collect_x",
        lambda value: (_ for _ in ()).throw(AssertionError("must reuse X")),
    )
    second = collect_current(target, at)
    rows = snapshot(at, target)

    assert first["observed"] == second["observed"] == 130
    assert second["audit"]["google_geo_kr"]["declared_total"] == 100
    assert second["audit"]["x_korea_realtime"]["row_count"] == 30
    assert {row["topic"] for row in rows if row["source"] == "google_trends"} == {
        f"첫구글{rank}" for rank in range(1, 101)
    }
    assert {row["topic"] for row in rows if row["source"] == "x"} == {
        f"첫X{rank}" for rank in range(1, 31)
    }


def test_verified_source_snapshot_replaces_rows_and_writes_audit_atomically(tmp_path):
    target = tmp_path / "verified.sqlite3"
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    upsert([HourlyObservation(stamp, "x", "old", 1, 100, "observed")], target)

    count = store_verified_source_snapshot(
        [
            HourlyObservation(stamp, "x", "불꽃축제", 1, 100, "observed"),
            HourlyObservation(stamp, "x", "블루레이", 2, 99, "observed"),
        ],
        source="x",
        collector="x_korea_realtime",
        detail="user Chrome page; South Korea marker verified",
        path=target,
    )

    assert count == 2
    assert [row["topic"] for row in snapshot(at, target)] == ["불꽃축제", "블루레이"]
    assert latest_audit(at, target)["x_korea_realtime"] == {
        "status": "observed",
        "row_count": 2,
        "detail": "user Chrome page; South Korea marker verified",
    }


def test_live_x_spam_is_rejected_before_persistence(tmp_path):
    target = tmp_path / "spam-rejected.sqlite3"
    stamp = datetime(2026, 8, 12, 4, tzinfo=UTC).isoformat()

    with pytest.raises(ValueError, match="solicitation/contact spam"):
        store_verified_source_snapshot(
            [HourlyObservation(
                stamp, "x", "출장만남 진행중", 1, 100, "observed",
                collector_version="x_current_session_kr_v1",
            )],
            source="x",
            collector="x_korea_realtime",
            detail="current Chrome",
            path=target,
        )

    assert snapshot(datetime.fromisoformat(stamp), target, live_only=True) == []


def test_historical_contaminated_x_hour_is_quarantined_without_reranking(tmp_path):
    target = tmp_path / "spam-quarantine.sqlite3"
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    with connect(target) as connection:
        connection.executemany(
            """INSERT INTO hourly_observations
               (observed_at,source,topic,source_rank,value,provenance,collector_version)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (stamp, "x", "출장만남 진행중", 1, 100, "observed", "x_current_session_kr_v1"),
                (stamp, "x", "불꽃축제", 2, 99, "observed", "x_current_session_kr_v1"),
                (stamp, "google_trends", "코믹월드", 1, 100, "observed", "google_trending_now_kr_v1"),
            ],
        )

    quality = source_hour_quality(at, at, target, live_only=True)

    assert next(row for row in quality if row["source"] == "x")["quality_status"] == (
        "quarantined_source_spam"
    )
    assert [row["source"] for row in snapshot(at, target, live_only=True)] == [
        "google_trends"
    ]


def test_google_web_rows_preserve_source_payload_and_related_terms(monkeypatch):
    from trzip.google_web_collector import GoogleTrend

    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    monkeypatch.setattr(
        "trzip.google_web_collector.collect_google_page",
        lambda **kwargs: ([GoogleTrend(
            1,
            "말복",
            "5천+",
            "1,000%",
            "2시간 전",
            ("삼계탕", "보양식"),
            {"volume_text": "5천+", "growth_text": "1,000%", "page": 1},
        )], {
            "row_count": 1,
            "declared_total": 1,
            "page_count": 1,
            "completion_verified": True,
        }),
    )

    rows = collect_google(at)

    assert [row.topic for row in rows] == ["말복"]
    assert json.loads(rows[0].source_payload_json)["volume_text"] == "5천+"
    assert json.loads(rows[0].source_payload_json)["collection_declared_total"] == 1
    assert json.loads(rows[0].source_payload_json)["collection_page_count"] == 1
    assert json.loads(rows[0].source_payload_json)["collection_completion_verified"] is True
    assert json.loads(rows[0].related_terms_json) == ["삼계탕", "보양식"]


def test_daily_aggregate_uses_only_quality_eligible_source_hours(tmp_path):
    target = tmp_path / "daily-quality.sqlite3"
    first = datetime(2026, 8, 12, 0, tzinfo=UTC)
    second = first + timedelta(hours=1)
    upsert([
        HourlyObservation(first.isoformat(), "x", "말복", 1, 100, "observed"),
        HourlyObservation(second.isoformat(), "x", "말복", 1, 100, "observed"),
        HourlyObservation(second.isoformat(), "x", "중복 순위", 1, 99, "observed"),
    ], target)

    quality = source_hour_quality(first, second, target)
    aggregates = daily_aggregates(date(2026, 8, 12), target)

    assert [row["quality_status"] for row in quality] == [
        "eligible", "quarantined_duplicate_rank",
    ]
    malbok = next(row for row in aggregates if row["topic"] == "말복")
    assert malbok["hours_present"] == 1
    assert malbok["observation_count"] == 1


def test_pre_v3_observations_are_preserved_but_quarantined_from_rankings(tmp_path):
    target = tmp_path / "legacy-cutover.sqlite3"
    at = datetime(2026, 8, 12, 0, tzinfo=UTC)
    with connect(target) as connection:
        connection.execute(
            """INSERT INTO hourly_observations
               (observed_at,source,topic,source_rank,value,provenance,collector_version)
               VALUES (?,?,?,?,?,?,NULL)""",
            (at.isoformat(), "x", "legacy-only", 1, 100, "observed"),
        )

    assert hourly_rankings(at, target) == []
    profile = coverage(target)
    assert profile["rows"] == 0
    assert profile["legacy_observed_rows"] == 1


def test_arbitrary_non_null_collector_version_is_rejected_and_quarantined(tmp_path):
    target = tmp_path / "collector-cohort.sqlite3"
    at = datetime(2026, 8, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="not approved"):
        upsert([
            HourlyObservation(
                at.isoformat(), "x", "untrusted", 1, 100, "observed",
                collector_version="manual_backfill_v0",
            ),
        ], target)

    # Raw evidence can still be preserved by migrations or explicit audit
    # tooling, but it cannot enter any production ranking view.
    with connect(target) as connection:
        connection.execute(
            """INSERT INTO hourly_observations
               (observed_at,source,topic,source_rank,value,provenance,collector_version)
               VALUES (?,?,?,?,?,?,?)""",
            (at.isoformat(), "x", "quarantined", 1, 100, "observed", "manual_backfill_v0"),
        )

    assert hourly_rankings(at, target) == []
    assert snapshot(at, target) == []
