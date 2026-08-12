from datetime import UTC, datetime

from trzip.curation import curate_raw_platform_items, reconstructed_demo_feed


def test_all_observed_terms_are_preserved_while_policy_issue_is_tagged():
    result = curate_raw_platform_items([
        {"rank": 1, "title": "국가장학금"}, {"rank": 2, "title": "정준하"},
        {"rank": 3, "title": "수건"}, {"rank": 4, "title": "불닭"},
    ])
    assert [row["title"] for row in result["main"]] == ["정준하", "수건", "불닭"]
    assert {row["title"] for row in result["issue"]} == {"국가장학금"}
    assert result["review"] == []


def test_demo_has_explicit_window_and_curated_main():
    result = reconstructed_demo_feed(datetime(2026, 7, 15, tzinfo=UTC))
    assert result["demo_window"] == {"from": "2026-05-01T00:00:00+09:00", "to": "2026-08-12T11:00:00+09:00"}
    assert result["is_live"] is False
    names = {row["title"] for row in result["lanes"]["main"]}
    assert {"불닭", "리센느", "오징어 게임"} <= names


def test_malbok_is_normalized_to_consumption_event():
    result = curate_raw_platform_items([{"rank": 1, "title": "말복"}])
    assert result["main"][0]["title"] == "말복"
    assert "삼계탕" in result["main"][0]["phenomenon_summary"]
    assert "삼계탕" in result["main"][0]["context_signals"]
