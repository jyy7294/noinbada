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
    assert contextualized["selection"] == "main"


def test_person_name_containing_phone_syllable_is_not_a_product_signal():
    result = assess_trend_fit("코디 폰세")

    assert result["selection"] == "review"
    assert result["labels"] == []


def test_sports_market_and_content_are_in_scope():
    assert assess_trend_fit("야구 직관", category="sports_attendance")["main_eligible"]
    assert assess_trend_fit("오징어 게임", category="screen_content")["main_eligible"]
    assert assess_trend_fit("삼성전자 주식", category="investment_market")["main_eligible"]
