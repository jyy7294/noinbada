import json

import pytest

from trzip.x_web_collector import (
    XCollectionError,
    XPageSnapshot,
    _classify_page_failure,
    _write_ready_marker,
    inspect_x_page,
    parse_trend_cells,
    ready_marker,
    wait_for_verified_page,
)


def test_parse_numbered_x_trends_and_skip_promoted_cell():
    cells = [
        "〈원신〉 7.0 버전\nPromoted by Genshin Impact",
        "1\n·\nOnly on X · 실시간 트렌드\n스네즈나",
        "2\n·\n대한민국에서 트렌드 중\n데이즈드",
        "3\n·\n뮤직 · 실시간 트렌드\n#SurfinBoy1stWin",
    ]
    result = parse_trend_cells(cells)
    assert [(item.rank, item.topic) for item in result] == [
        (1, "스네즈나"),
        (2, "데이즈드"),
        (3, "#SurfinBoy1stWin"),
    ]


def test_parse_deduplicates_topic_without_renumbering_source_rank():
    result = parse_trend_cells([
        "1\n·\n대한민국에서 트렌드 중\n불꽃축제",
        "4\n·\nOnly on X · 실시간 트렌드\n불꽃축제",
    ])
    assert [(item.rank, item.topic) for item in result] == [(1, "불꽃축제")]


def test_login_page_is_classified_for_operator_action():
    failure = _classify_page_failure("https://x.com/i/flow/login", "X에 로그인", 0)
    assert isinstance(failure, XCollectionError)
    assert failure.code == "auth_required"


def test_current_x_onboarding_login_page_is_classified_as_auth_required():
    failure = _classify_page_failure(
        "https://x.com/i/jf/onboarding/web?redirect_after_login=%2Fexplore%2Ftabs%2Ftrending&mode=login",
        "전화번호로 계속\n이메일 또는 사용자 이름\n계속하기",
        0,
    )
    assert failure.code == "auth_required"


def test_missing_cells_is_selector_change():
    failure = _classify_page_failure("https://x.com/explore/tabs/trending", "탐색하기", 0)
    assert failure.code == "selector_changed"


def test_dedicated_profile_uses_explicit_ready_marker(tmp_path):
    assert ready_marker(tmp_path) == tmp_path / ".trzip-x-ready"


def _korea_cells(count=10):
    return [f"{rank}\n·\n대한민국에서 트렌드 중\n주제 {rank}" for rank in range(1, count + 1)]


def test_page_inspection_requires_explicit_korea_evidence_even_with_rows():
    snapshot = XPageSnapshot(
        url="https://x.com/explore/tabs/trending",
        body_text="실시간 트렌드",
        cells=[f"{rank}\n·\n실시간 트렌드\nTopic {rank}" for rank in range(1, 11)],
    )
    with pytest.raises(XCollectionError) as caught:
        inspect_x_page(snapshot)
    assert caught.value.code == "region_unverified"


def test_page_inspection_accepts_english_south_korea_marker():
    snapshot = XPageSnapshot(
        url="https://x.com/explore/tabs/trending",
        body_text="Trending in South Korea",
        cells=[f"{rank}\n·\nTrending in South Korea\nTopic {rank}" for rank in range(1, 11)],
    )
    trends, audit = inspect_x_page(snapshot)
    assert len(trends) == 10
    assert audit["region"] == "KR"
    assert audit["region_verified"] is True


def test_setup_polling_waits_through_login_without_enter():
    snapshots = iter([
        XPageSnapshot("https://x.com/i/flow/login", "X에 로그인", []),
        XPageSnapshot("https://x.com/explore/tabs/trending", "불러오는 중", []),
        XPageSnapshot(
            "https://x.com/explore/tabs/trending",
            "대한민국에서 트렌드 중",
            _korea_cells(),
        ),
    ])
    clock = {"value": 0.0}

    def pause(seconds):
        clock["value"] += seconds

    trends, audit = wait_for_verified_page(
        lambda: next(snapshots),
        timeout_seconds=600,
        retry_auth=True,
        pause=pause,
        now=lambda: clock["value"],
    )
    assert len(trends) == 10
    assert audit["status"] == "observed"


def test_normal_collection_reports_auth_after_opening_page():
    snapshot = XPageSnapshot("https://x.com/i/flow/login", "Sign in to X", [])
    with pytest.raises(XCollectionError) as caught:
        wait_for_verified_page(
            lambda: snapshot,
            timeout_seconds=30,
            retry_auth=False,
            pause=lambda seconds: None,
        )
    assert caught.value.code == "auth_required"


def test_success_marker_records_page_evidence(tmp_path):
    _write_ready_marker(tmp_path, 12)
    payload = json.loads(ready_marker(tmp_path).read_text(encoding="utf-8"))
    assert payload["region"] == "KR"
    assert payload["row_count"] == 12
