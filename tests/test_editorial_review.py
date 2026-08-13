from trzip.editorial_review import build_editorial_review_pack


def test_editorial_review_pack_only_includes_concrete_registered_terms():
    rows = [
        {"rank": 1, "event_key": "food", "display_name": "음식", "score": 90,
         "period_sources": ["google_trends"]},
        {"rank": 2, "event_key": "iphone", "display_name": "아이폰", "score": 80,
         "period_sources": ["google_trends"]},
        {"rank": 3, "event_key": "unknown", "display_name": "아무 단어", "score": 70,
         "period_sources": ["x"]},
    ]
    pack = build_editorial_review_pack({"unified_ranking": rows})
    assert [item["display_name"] for item in pack["trends"]] == ["아이폰"]
    assert all(len(item["related_keyword_candidates"]) == 15 for item in pack["trends"])
    assert all(len(item["company_candidates"]) >= 3 for item in pack["trends"])
    assert all(company["ranking_effect"] == "none" for item in pack["trends"] for company in item["company_candidates"])
    assert all(company["company_description"] for item in pack["trends"] for company in item["company_candidates"])
    assert pack["trends"][0]["company_display_policy"]["show_category_groups"] is False
    assert pack["candidate_policy"]["padding_forbidden"] is True
    assert pack["candidate_policy"]["broad_term_forbidden"] is True


def test_editorial_review_pack_does_not_modify_observed_rank_or_score():
    source = {
        "unified_ranking": [{
            "rank": 7,
            "event_key": "iphone",
            "display_name": "아이폰",
            "score": 58.0,
            "broad_category": "food",
            "period_sources": ["google_trends"],
        }]
    }
    pack = build_editorial_review_pack(source)
    assert pack["trends"][0]["observed_rank"] == 7
    assert pack["trends"][0]["score"] == 58.0
    assert pack["trends"][0]["source_evidence_urls"] == [
        "https://trends.google.com/trending?geo=KR"
    ]


def test_company_shortfall_is_reported_without_padding():
    source = {"unified_ranking": [{
        "rank": 1, "event_key": "fireworks", "display_name": "불꽃축제", "score": 50,
        "period_sources": ["google_trends"],
    }]}
    item = build_editorial_review_pack(source)["trends"][0]
    assert len(item["company_candidates"]) == 0
    assert item["company_verification_status"] == "insufficient_verified_companies"
