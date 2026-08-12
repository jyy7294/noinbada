import sqlite3
from datetime import UTC, datetime, timedelta

from trzip.enrichment_queue import sync_enrichment_queue


def _trend(rank, key, keywords=0, companies=0, lane="main"):
    return {
        "rank": rank,
        "event_key": key,
        "display_name": key,
        "raw_terms": [key],
        "keywords": [
            {"text": f"{key}-keyword-{index}"} for index in range(keywords)
        ],
        "lane": lane,
        "company_resolution": {"candidate_count": companies},
    }


def test_queue_persists_all_ranked_gaps_without_changing_intelligence(tmp_path):
    at = datetime(2026, 8, 13, tzinfo=UTC)
    trends = [_trend(1, "complete", 5, 5), _trend(2, "gap", 1, 0)]
    intelligence = {"unified_ranking": trends, "public_top10": trends}
    before = repr(intelligence)

    result = sync_enrichment_queue(intelligence, path=tmp_path / "queue.sqlite3", at=at)

    assert repr(intelligence) == before
    assert result["counts"] == {
        "company_ontology": {"pending": 1, "complete": 1},
        "related_keywords": {"pending": 1, "complete": 1},
    }
    assert result["pending_total"] == 2
    assert {item["task_kind"] for item in result["pending"]} == {
        "company_ontology", "related_keywords",
    }
    assert all(item["affects_score"] is False for item in result["pending"])
    assert all(item["representative_term"] == "gap" for item in result["pending"])


def test_queue_is_idempotent_per_hour_and_keeps_history_across_hours(tmp_path):
    path = tmp_path / "queue.sqlite3"
    first_at = datetime(2026, 8, 13, tzinfo=UTC)
    first = {"unified_ranking": [_trend(1, "trend", 0, 0)], "public_top10": []}
    second = {"unified_ranking": [_trend(3, "trend", 5, 5)], "public_top10": []}

    sync_enrichment_queue(first, path=path, at=first_at)
    sync_enrichment_queue(first, path=path, at=first_at)
    result = sync_enrichment_queue(second, path=path, at=first_at + timedelta(hours=1))

    assert result["pending_total"] == 0
    assert result["tracked_observations"] == 4
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM enrichment_tasks").fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM enrichment_task_observations"
        ).fetchone()[0] == 4


def test_public_rows_have_higher_research_priority_than_hidden_rows(tmp_path):
    path = tmp_path / "queue.sqlite3"
    hidden = _trend(1, "hidden", lane="review")
    visible = _trend(50, "visible", lane="main")
    result = sync_enrichment_queue(
        {"unified_ranking": [hidden, visible], "public_top10": [visible]},
        path=path,
        at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert [item["event_key"] for item in result["pending"][:2]] == ["visible", "visible"]
