from trzip.source_adjudication import adjudicate_source_expression


def test_concrete_terms_are_included_with_one_of_eight_categories():
    assert adjudicate_source_expression("\ucf54\ub09c \uadf9\uc7a5\ud310").as_dict()["decision"] == "included"
    eclipse = adjudicate_source_expression("\uac1c\uae30\uc77c\uc2dd").as_dict()
    assert eclipse["decision"] == "included"
    assert eclipse["broad_category"] == "culture"


def test_sensitive_and_generic_terms_finish_without_a_review_state():
    assert adjudicate_source_expression("\uad6d\ud68c \uc120\uac70").as_dict()["decision"] == "excluded"
    assert adjudicate_source_expression("\uc790\ub3d9\ucc28").as_dict()["decision"] == "not_selected"
    assert adjudicate_source_expression("\uae40\uc131\uc5f0").as_dict()["decision"] == "not_selected"
    assert adjudicate_source_expression("\uacbd\uae30\ub3c4\uad50\uc721\uccad").as_dict()["decision"] == "not_selected"
    assert adjudicate_source_expression("\uc778\uacf5\uc9c0\ub2a5").as_dict()["decision"] == "not_selected"


def test_hashtag_without_concrete_context_is_finally_not_selected():
    result = adjudicate_source_expression("#MakeAWishForJaemin").as_dict()
    assert result["decision"] == "not_selected"
    assert result["finality"] == "final_for_source_only_run"


def test_sports_needs_a_fixture_or_named_outcome_not_a_standing_or_team_name():
    assert adjudicate_source_expression("kbo \uc21c\uc704").as_dict()["decision"] == "not_selected"
    assert adjudicate_source_expression("\uac15\uc6d0 fc").as_dict()["decision"] == "not_selected"
    assert adjudicate_source_expression("\uba54\uce20 \ub300 \ube0c\ub808\uc774\ube0c\uc2a4").as_dict()["decision"] == "included"
