import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trzip.x_web_collector import (
    XCollectionError,
    XPageSnapshot,
    _validate_bridge_payload,
    collect_x_page,
    inspect_x_page,
    parse_trend_cells,
)


def test_parse_numbered_x_trends_and_skip_promoted_cell():
    cells = [
        "원신 7.0 버전\nPromoted by Genshin Impact",
        "1\n·\nOnly on X · 실시간 트렌드\n스넬즈나",
        "2\n·\n대한민국에서 트렌드 중\n웨이즈드",
        "3\n·\nMusic · Trending\n#SurfinBoy1stWin",
    ]
    result = parse_trend_cells(cells)
    assert [(item.rank, item.topic) for item in result] == [
        (1, "스넬즈나"),
        (2, "웨이즈드"),
        (3, "#SurfinBoy1stWin"),
    ]


def test_page_inspection_requires_korea_and_all_thirty_rows():
    rows = [f"{rank}\n·\n대한민국에서 트렌드 중\n주제 {rank}" for rank in range(1, 30)]
    with pytest.raises(XCollectionError) as caught:
        inspect_x_page(XPageSnapshot("https://x.com/explore/tabs/trending", "대한민국 트렌드", rows))
    assert caught.value.code == "incomplete_scroll"


def _payload(observed_at: str, count: int = 30) -> dict:
    return {
        "schema_version": 1,
        "source": "x",
        "collector": "chrome_extension_current_session",
        "observed_at": observed_at,
        "scheduled_for": "2026-08-12T12:00:00Z",
        "url": "https://x.com/explore/tabs/trending",
        "region": "KR",
        "region_verified": True,
        "row_count": count,
        "trends": [{"rank": rank, "topic": f"주제 {rank}"} for rank in range(1, count + 1)],
    }


def test_current_hour_bridge_accepts_complete_rank_1_to_30():
    now = datetime(2026, 8, 12, 12, 10, tzinfo=UTC)
    trends, audit = _validate_bridge_payload(
        _payload("2026-08-12T12:00:04Z"),
        now=now,
        minimum_rows=10,
    )
    assert len(trends) == 30
    assert audit["collector"] == "chrome_extension_current_session"
    assert audit["transport"] == "sanitized_download_inbox"
    assert audit["schedule_delay_seconds"] == 4


def test_current_hour_bridge_accepts_codex_logged_in_chrome_collector():
    now = datetime(2026, 8, 12, 12, 10, tzinfo=UTC)
    payload = _payload("2026-08-12T12:00:20Z")
    payload["collector"] = "codex_chrome_current_session"

    trends, audit = _validate_bridge_payload(
        payload,
        now=now,
        minimum_rows=30,
    )

    assert len(trends) == 30
    assert audit["collector"] == "codex_chrome_current_session"
    assert audit["transport"] == "codex_browser_snapshot"


def test_current_hour_bridge_rejects_unknown_collector():
    payload = _payload("2026-08-12T12:00:20Z")
    payload["collector"] = "unknown"

    with pytest.raises(XCollectionError, match="unsupported X snapshot collector"):
        _validate_bridge_payload(
            payload,
            now=datetime(2026, 8, 12, 12, 10, tzinfo=UTC),
            minimum_rows=30,
        )


def test_previous_hour_bridge_is_rejected_as_stale():
    with pytest.raises(XCollectionError) as caught:
        _validate_bridge_payload(
            _payload("2026-08-12T11:59:59Z"),
            now=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            minimum_rows=30,
        )
    assert caught.value.code == "snapshot_stale"


def test_bridge_rejects_missing_rank_even_when_row_count_is_thirty():
    payload = _payload("2026-08-12T12:00:04Z")
    payload["trends"][-1] = {"rank": 31, "topic": "주제 31"}
    with pytest.raises(XCollectionError) as caught:
        _validate_bridge_payload(
            payload,
            now=datetime(2026, 8, 12, 12, 1, tzinfo=UTC),
            minimum_rows=30,
        )
    assert caught.value.code == "incomplete_scroll"


def test_collect_x_reads_sanitized_inbox_without_launching_browser(tmp_path):
    inbox = tmp_path / "x-current-session.json"
    inbox.write_text(json.dumps(_payload("2026-08-12T12:00:04Z"), ensure_ascii=False), encoding="utf-8")
    trends, audit = collect_x_page(
        inbox_file=inbox,
        timeout_ms=1,
        minimum_rows=30,
        now=lambda: datetime(2026, 8, 12, 12, 1, tzinfo=UTC),
        pause=lambda _seconds: None,
    )
    assert trends[0].topic == "주제 1"
    assert trends[-1].rank == 30
    assert audit["profile"] == "current_logged_in_chrome"


def test_missing_extension_inbox_fails_immediately(tmp_path):
    with pytest.raises(XCollectionError) as caught:
        collect_x_page(
            inbox_file=tmp_path / "missing.json",
            timeout_ms=120_000,
            pause=lambda _seconds: pytest.fail("missing setup must not sleep"),
        )
    assert caught.value.code == "extension_not_ready"


def test_extension_has_no_cookie_or_storage_permission_and_only_x_trending_host():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((
        root / "chrome-extension" / "trzip-x-current-session" / "manifest.json"
    ).read_text(encoding="utf-8"))
    assert "cookies" not in manifest["permissions"]
    assert "storage" not in manifest["permissions"]
    assert manifest["host_permissions"] == ["https://x.com/explore/tabs/trending*"]
    worker = (
        root / "chrome-extension" / "trzip-x-current-session" / "service-worker.js"
    ).read_text(encoding="utf-8")
    assert "persistAcrossSessions: true" in worker
    assert 'const OUTPUT_FILE = "TRZIP/x-current-session.json"' in worker


def test_setup_uses_chrome_last_used_profile_by_default():
    root = Path(__file__).resolve().parents[1]
    setup = (root / "scripts" / "setup-x-chrome.ps1").read_text(encoding="utf-8")

    assert '[string]$ProfileName = ""' in setup
    assert "$LocalState.profile.last_used" in setup
    assert '"--profile-directory=$ProfileDirectory"' in setup
