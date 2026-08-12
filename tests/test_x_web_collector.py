from trzip.x_web_collector import XCollectionError, _classify_page_failure, parse_trend_cells, ready_marker


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


def test_missing_cells_is_selector_change():
    failure = _classify_page_failure("https://x.com/explore/tabs/trending", "탐색하기", 0)
    assert failure.code == "selector_changed"


def test_dedicated_profile_uses_explicit_ready_marker(tmp_path):
    assert ready_marker(tmp_path) == tmp_path / ".trzip-x-ready"
