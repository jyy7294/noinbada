import pytest

from trzip.google_web_collector import (
    GOOGLE_TRENDS_URL,
    GoogleCollectionError,
    normalize_row,
    validate_complete_rows,
)


def _row(index: int) -> dict:
    return {
        "topic": f"주제 {index}",
        "volume_text": "5천+",
        "growth_text": "1,000%",
        "started_text": f"{index}시간 전",
        "status_text": "활성",
        "related_terms": [f"연관 {index}", f"연관 {index}", ""],
        "page": (index - 1) // 25 + 1,
        "row_on_page": (index - 1) % 25 + 1,
    }


def test_google_url_is_korea_trending_now_page_not_rss():
    assert GOOGLE_TRENDS_URL == "https://trends.google.com/trending?geo=KR&hl=ko"
    assert "rss" not in GOOGLE_TRENDS_URL


def test_normalize_row_preserves_metrics_and_deduplicates_related_terms():
    row = normalize_row(_row(1), 1)
    assert row.topic == "주제 1"
    assert row.volume_text == "5천+"
    assert row.growth_text == "1,000%"
    assert row.started_text == "1시간 전"
    assert row.related_terms == ("연관 1",)
    assert row.source_payload["page"] == 1


def test_complete_google_collection_uses_live_declared_total_not_hardcoded_182():
    raw = [_row(index) for index in range(1, 182)]
    rows = validate_complete_rows(raw, declared_total=181, minimum_rows=100)
    assert len(rows) == 181
    assert rows[-1].rank == 181


def test_missing_last_page_fails_completion_gate():
    raw = [_row(index) for index in range(1, 176)]
    with pytest.raises(GoogleCollectionError) as caught:
        validate_complete_rows(raw, declared_total=181, minimum_rows=100)
    assert caught.value.code == "incomplete_pages"


def test_duplicate_page_rows_fail_instead_of_silent_deduplication():
    raw = [_row(index) for index in range(1, 101)]
    raw[-1] = dict(raw[0])
    with pytest.raises(GoogleCollectionError) as caught:
        validate_complete_rows(raw, declared_total=100, minimum_rows=100)
    assert caught.value.code == "duplicate_rows"
