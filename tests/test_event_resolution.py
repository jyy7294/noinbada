from trzip.event_resolution import GROUND_TRUTH, relation_display, resolve_event


def test_ground_truth_has_at_least_thirty_cases():
    assert len(GROUND_TRUTH) >= 30


def test_bloody_game_is_screen_content_not_digital_game():
    event = resolve_event("피의 게임", {"google_trends"})
    assert event["category"] == "screen_content"
    assert "Google Trends KR" in event["phenomenon_summary"]
    assert "X 한국" not in event["phenomenon_summary"]


def test_unknown_person_name_is_not_falsely_resolved():
    event = resolve_event("홍길동", {"x"})
    assert event["context_status"] == "ambiguous_person"
    assert event["phenomenon_summary"] == '"홍길동" · X 한국 실시간에서 관측'
    assert "논란" not in event["phenomenon_summary"]


def test_company_relation_and_team_review_are_separate():
    company = {"company": "관찰기업", "relation_tier": "adjacent", "evidence_url": None}
    display = relation_display(company, {})
    assert display["relation_display_type"] == "산업 관찰"
    assert display["team_review_status"] == "unreviewed"


def test_stock_code_and_fireworks_are_resolved_without_invented_event_names():
    stock = resolve_event("005930", {"google_trends"})
    festival = resolve_event("불꽃축제", {"x"})

    assert stock["canonical"] == "삼성전자"
    assert stock["category"] == "investment_market"
    assert festival["canonical"] == "불꽃축제"
    assert festival["category"] == "place_experience"
