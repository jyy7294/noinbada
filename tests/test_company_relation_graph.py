from trzip.company_relation_graph import resolve_listed_parent


def test_x_resolves_to_listed_spacex_only_through_the_sourced_owner_path():
    result = resolve_listed_parent("X")

    assert result["status"] == "resolved"
    assert result["company"] == "SpaceX"
    assert result["ticker"] == "SPCX"
    assert result["market"] == "NASDAQ"
    assert result["path"] == ["X", "xAI", "SpaceX"]
    assert result["relation_types"] == ["common_parent", "acquired_by"]
    assert len(result["evidence_urls"]) == 2
    assert result["listing_evidence_url"].startswith("https://ir.spacex.com/")


def test_shared_founder_does_not_create_an_unreviewed_listed_parent():
    result = resolve_listed_parent("Tesla")

    assert result["status"] == "not_found"
