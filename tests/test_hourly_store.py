from datetime import UTC, datetime

from trzip.hourly_store import (
    HourlyObservation,
    collect_current,
    demo_topics,
    generated_hour,
    latest_audit,
    snapshot,
    store_verified_source_snapshot,
    upsert,
)


def test_observed_and_generated_rows_coexist_without_overwrite(tmp_path):
    target = tmp_path / "coexist.sqlite3"
    at = datetime(2026, 8, 12, 2, tzinfo=UTC)
    stamp = at.isoformat()
    upsert([
        HourlyObservation(stamp, "google_trends", "말복", 3, 98, "generated"),
        HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed"),
    ], target)
    rows = snapshot(at, target)
    assert len(rows) == 2
    assert {row["provenance"] for row in rows} == {"generated", "observed"}


def test_scheduled_collection_never_calls_trends_mcp(tmp_path, monkeypatch):
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    monkeypatch.setenv("TRENDS_MCP_API_KEY", "configured-but-disabled")
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: [])

    def forbidden(*args, **kwargs):
        raise AssertionError("scheduled collection must not call Trends MCP")

    monkeypatch.setattr("trzip.hourly_store.collect_trends_mcp", forbidden)
    result = collect_current(tmp_path / "hourly.sqlite3", at, use_trends_mcp=False)

    assert result["trends_mcp_used"] is False
    assert result["audit"]["google_trends_mcp"]["status"] == "disabled"


def test_explicit_one_time_probe_can_call_trends_mcp(tmp_path, monkeypatch):
    at = datetime(2026, 8, 12, 4, tzinfo=UTC)
    stamp = at.isoformat()
    monkeypatch.setenv("TRENDS_MCP_API_KEY", "configured")
    monkeypatch.setattr(
        "trzip.hourly_store.collect_google",
        lambda value: [HourlyObservation(stamp, "google_trends", "말복", 1, 100, "observed")],
    )
    monkeypatch.setattr("trzip.hourly_store.collect_x", lambda value: [])
    monkeypatch.setattr(
        "trzip.hourly_store.collect_trends_mcp",
        lambda *args: [HourlyObservation(stamp, "google_trends", "global probe", 1, 100, "observed")],
    )

    result = collect_current(tmp_path / "hourly.sqlite3", at, use_trends_mcp=True)

    assert result["trends_mcp_used"] is True
    assert result["audit"]["google_trends_mcp"]["row_count"] == 1


def test_demo_topics_expire_instead_of_staying_ranked_forever():
    may = generated_hour(datetime(2026, 5, 15, 3, tzinfo=UTC))
    august = generated_hour(datetime(2026, 8, 10, 3, tzinfo=UTC))
    assert any(row.topic == "오징어 게임" for row in may)
    assert all(row.topic != "오징어 게임" for row in august)
    assert "말복" in demo_topics(datetime(2026, 8, 10, 3, tzinfo=UTC))


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
