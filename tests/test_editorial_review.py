from trzip.editorial_review import build_editorial_review_pack


def test_editorial_review_pack_is_three_times_the_public_selection_target():
    rows = []
    categories = ("food", "consumer", "lifestyle", "culture", "technology", "content")
    for index in range(36):
        rows.append({
            "rank": index + 1,
            "event_key": f"event-{index}",
            "display_name": f"트렌드 {index}",
            "score": 100 - index,
            "broad_category": categories[index % len(categories)],
            "period_sources": ["x"] if index % 2 else ["google_trends"],
        })
    pack = build_editorial_review_pack({"unified_ranking": rows})
    assert len(pack["trends"]) == 30
    assert all(len(item["related_keyword_candidates"]) == 15 for item in pack["trends"])
    assert all(len(item["company_candidates"]) == 9 for item in pack["trends"])
    assert all(company["ranking_effect"] == "none" for item in pack["trends"] for company in item["company_candidates"])
    assert pack["candidate_policy"]["approval_required"] is True
    assert pack["candidate_policy"]["official_relationship_required"] is False


def test_editorial_review_pack_does_not_modify_observed_rank_or_score():
    source = {
        "unified_ranking": [{
            "rank": 7,
            "event_key": "coffee",
            "display_name": "커피믹스",
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
