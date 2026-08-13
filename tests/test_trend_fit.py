from trzip.trend_fit import assess_trend_fit


def test_consumer_culture_terms_are_main_without_score_effect():
    result = assess_trend_fit(
        "양즈깐루",
        category="food_culinary",
        context_terms=["편의점 신메뉴 출시", "카페 판매", "SNS 여행 후기"],
        news_claim_types=["search_growth", "product_launch", "sales_rank", "consumer_behavior"],
    )
    assert result["selection"] == "main"
    assert {"named_object", "productization", "consumer_action"} <= set(result["labels"])
    assert result["rank_effect"] == "none"


def test_politics_incident_and_plain_alert_go_to_issue_lane():
    for term in ("국방부 논란", "거제경찰서 폭행", "서울 폭염경보"):
        assert assess_trend_fit(term)["selection"] == "issue"


def test_unknown_generic_term_is_preserved_for_review():
    result = assess_trend_fit("수건")
    assert result["selection"] == "review"
    assert result["ambiguous"] is True


def test_broad_taxonomy_word_needs_specific_context_before_main():
    generic = assess_trend_fit(
        "음식",
        category="food_culinary",
        context_terms=["습관"],
    )
    contextualized = assess_trend_fit(
        "음식",
        category="food_culinary",
        context_terms=["치킨 신메뉴 출시"],
    )

    assert generic["selection"] == "review"
    assert generic["generic_category_word"] is True
    assert generic["rank_effect"] == "none"
    assert contextualized["selection"] == "review"


def test_person_name_containing_phone_syllable_is_not_a_product_signal():
    result = assess_trend_fit("코디 폰세")

    assert result["selection"] == "review"
    assert result["labels"] == []


def test_sports_market_and_content_are_in_scope():
    assert assess_trend_fit("야구 직관", category="sports_attendance")["main_eligible"]
    assert assess_trend_fit("오징어 게임", category="screen_content")["main_eligible"]
    assert assess_trend_fit("삼성전자 주식", category="investment_market")["main_eligible"]
    assert assess_trend_fit("관리종목", category="investment_market")["main_eligible"]


def test_provider_title_can_demote_legal_event_but_never_promote_a_term():
    legal = assess_trend_fit(
        "삼성증권",
        category="investment_market",
        issue_context_terms=["대법원 유령주식 사건 18억 원 배상 판결"],
    )
    ordinary = assess_trend_fit(
        "삼성증권",
        category="investment_market",
        issue_context_terms=["삼성증권 투자 설명회"],
    )

    assert legal["selection"] == "issue"
    assert legal["issue_context_used"] is True
    # The raw market noun "증권" is itself a general lexical signal; the
    # provider title does not create that eligibility.
    assert ordinary["selection"] == "main"
    assert ordinary["rank_effect"] == "none"


def test_issue_marker_is_not_created_across_whitespace_boundary():
    result = assess_trend_fit("보고 소원 트렌드")

    assert result["selection"] == "review"
    assert result["hard_issue"] is False


def test_single_soft_provider_title_does_not_demote_the_whole_trend():
    one_title = assess_trend_fit(
        "미스코리아",
        category="screen_content",
        issue_context_terms=["미스코리아 출연자 사생활 이야기"],
    )
    corroborated = assess_trend_fit(
        "미스코리아",
        category="screen_content",
        issue_context_terms=[
            "미스코리아 출연자 사생활 이야기",
            "미스코리아 관련 사생활 논란 후속 보도",
        ],
    )

    assert one_title["selection"] == "review"
    assert one_title["hard_issue"] is False
    assert one_title["provider_soft_issue_match_count"] == 1
    assert corroborated["selection"] == "issue"
    assert corroborated["provider_soft_issue_match_count"] == 2
