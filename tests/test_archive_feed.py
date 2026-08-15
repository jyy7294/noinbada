from __future__ import annotations

import json
from pathlib import Path

from trzip.archive_feed import load_archive_source


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "reconstructed" / "trzip-final-50-20260814"
FRONTEND_FEED = ROOT / "frontend" / "trend-archive.json"


def _non_whitespace_length(value: str) -> int:
    return len("".join(value.split()))


def test_archive_is_a_non_ranking_projection_of_the_reviewed_fifty() -> None:
    feed = load_archive_source(SOURCE / "events.ndjson", SOURCE / "manifest.json")
    assert feed["schema_version"] == "trzip-archive-feed-v1"
    assert feed["data_mode"] == "reconstructed_reference"
    assert feed["live_eligible"] is False
    assert feed["ranking_eligible"] is False
    assert feed["ranking_effect"] == "none"
    assert feed["item_count"] == 50
    assert "rank" not in feed
    assert all("rank" not in item for item in feed["items"])
    assert all(item["why_now"] and item["evidence_urls"] for item in feed["items"])
    assert all(0 < len(item["companies"]) <= 3 for item in feed["items"])
    assert all(
        _non_whitespace_length(keyword) <= 6
        for item in feed["items"]
        for keyword in item["keywords"]
    )


def test_committed_frontend_archive_matches_the_builder() -> None:
    expected = load_archive_source(SOURCE / "events.ndjson", SOURCE / "manifest.json")
    actual = json.loads(FRONTEND_FEED.read_text(encoding="utf-8"))
    assert actual == expected
