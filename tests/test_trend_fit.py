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


def test_contact_solicitation_spam_never_enters_product_lanes():
    for term in (
        "출장만남 진행중",
        "빠른이동 연락",
        "군인 가능",
        "라인 qq750",
        "꼬들 1688",
        "사모님 고수입",
        "고수익 단기",
    ):
        result = assess_trend_fit(term)
        assert result["selection"] == "issue"
        assert result["spam_solicitation"] is True
        assert result["main_eligible"] is False


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


def test_broad_place_region_activity_and_content_words_stay_in_review():
    for term, category in (
        ("수영장", "place_experience"),
        ("유럽", "place_experience"),
        ("특집 예능", "screen_content"),
        ("테니스", "sports_participation"),
    ):
        result = assess_trend_fit(term, category=category)
        assert result["selection"] == "review"
        assert result["generic_category_word"] is True
        assert result["rank_effect"] == "none"


def test_bare_general_subjects_do_not_enter_main_lane():
    for term, category in (
        ("라면", "food_culinary"),
        ("한복", "fashion_collectible"),
        ("반도체", "technology_tool"),
        ("삼계탕", "food_culinary"),
    ):
        result = assess_trend_fit(term, category=category)
        assert result["selection"] == "review"
        assert result["generic_category_word"] is True


def test_standalone_market_entity_needs_a_current_market_event():
    standalone = assess_trend_fit(
        "미래에셋",
        category="investment_market",
        context_terms=["미래에셋 투자 설명회"],
    )
    triggered = assess_trend_fit("미래에셋 실적", category="investment_market")

    assert standalone["selection"] == "review"
    assert standalone["standalone_market_subject"] is True
    assert triggered["selection"] == "main"


def test_standalone_corporate_name_needs_a_trigger_but_product_service_can_remain():
    for term, category in (
        ("LG그룹", "technology_tool"),
        ("LG이노텍", "technology_tool"),
        ("삼성증권", "investment_market"),
    ):
        result = assess_trend_fit(term, category=category, context_terms=["휴머노이드"])
        assert result["selection"] == "review"
        assert result["standalone_corporate_subject"] is True

    assert assess_trend_fit("아이폰", category="product_brand")["selection"] == "main"
    assert assess_trend_fit("코난 극장판", category="screen_content")["selection"] == "main"


def test_sports_subject_requires_a_specific_fixture_or_event():
    subject = assess_trend_fit("베트남 축구 국가대표팀", category="sports_participation")
    fixture = assess_trend_fit("한국 vs 일본 농구", category="sports_participation")
    participation = assess_trend_fit("한국 vs 일본 농구 결승", category="sports_participation")

    assert subject["selection"] == "review"
    assert subject["nonspecific_sports_subject"] is True
    assert fixture["selection"] == "main"
    assert fixture["plain_sports_fixture"] is True
    assert participation["selection"] == "main"
    assert participation["plain_sports_fixture"] is False


def test_person_name_containing_phone_syllable_is_not_a_product_signal():
    result = assess_trend_fit("코디 폰세")

    assert result["selection"] == "review"
    assert result["labels"] == []


def test_sports_market_and_content_are_in_scope():
    assert assess_trend_fit("야구 직관", category="sports_attendance")["main_eligible"]
    assert assess_trend_fit("오징어 게임", category="screen_content")["main_eligible"]
    assert assess_trend_fit("삼성전자 주식", category="investment_market")["main_eligible"]
    assert assess_trend_fit("관리종목", category="investment_market")["main_eligible"]


def test_observed_named_titles_and_fandom_events_need_no_context_enrichment():
    terms = (
        "둠스데이",
        "미스터 시니스터",
        "놀토",
        "겨울왕국",
        "엑스맨",
        "베리즈 라이브",
        "세츠나하나비",
        "월즈 진출",
        "UFC 330",
        "그래미 어워드",
        "콜 오브 듀티",
        "스타파이터",
        "어것디 10주년",
        "오시온 버블",
        "재벌형사",
        "미스 인도네시아",
        "#광복절",
        "독립운동가",
        "순국선열",
    )

    for term in terms:
        result = assess_trend_fit(term)
        assert result["selection"] == "main"
        assert result["main_eligible"] is True
        assert result["reviewed_named_trend"] is True
        assert "named_object" in result["labels"]
        assert result["news_context_used"] is False
        assert result["rank_effect"] == "none"


def test_named_trend_allowlist_never_overrides_safety_filters():
    assert assess_trend_fit("출장 만남")["selection"] == "issue"
    assert assess_trend_fit("체포")["selection"] == "issue"


def test_unapproved_ambiguous_title_is_not_silently_promoted():
    assert assess_trend_fit("타짜")["selection"] == "review"
    assert assess_trend_fit("#겹친소")["selection"] == "review"
    for term in (
        "사장님 귀는 당나귀 귀",
        "이혼숙려캠프: 새로고침",
        "JIN IN ARLINGTON D1",
        "삼성 갤럭시 S26",
        "사랑이 온다",
    ):
        assert assess_trend_fit(term)["selection"] == "review"


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
    # A company name alone is an observed search subject, not a current event.
    # Provider text may explain it but cannot silently promote it.
    assert ordinary["selection"] == "review"
    assert ordinary["standalone_market_subject"] is True
    assert ordinary["rank_effect"] == "none"


def test_issue_marker_is_not_created_across_whitespace_boundary():
    result = assess_trend_fit("보고 소원 트렌드")

    assert result["selection"] == "review"
    assert result["hard_issue"] is False


def test_arrest_and_public_subsidy_terms_route_to_issue_lane():
    assert assess_trend_fit("체포")["selection"] == "issue"
    assert assess_trend_fit("민생 지원금 지급일")["selection"] == "issue"


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
