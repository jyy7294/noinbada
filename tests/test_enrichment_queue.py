import sqlite3
from datetime import UTC, datetime, timedelta

from trzip.enrichment_queue import initialize_enrichment_queue, sync_enrichment_queue


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
        "context_research": {"status": "ready"},
    }


def test_queue_uses_frontend_related_keywords_before_raw_candidates(tmp_path):
    trend = _trend(1, "reviewed-ready", keywords=2, companies=6)
    trend["related_keywords"] = [
        {"text": f"reviewed-{index}", "source": ["reviewed_ontology"]}
        for index in range(5)
    ]

    result = sync_enrichment_queue(
        {"unified_ranking": [trend], "public_top10": [trend]},
        path=tmp_path / "queue.sqlite3",
        at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert result["counts"]["related_keywords"] == {"pending": 0, "complete": 1}
    assert not any(
        item["event_key"] == "reviewed-ready"
        and item["task_kind"] == "related_keywords"
        for item in result["pending"]
    )


def test_queue_persists_all_ranked_gaps_without_changing_intelligence(tmp_path):
    at = datetime(2026, 8, 13, tzinfo=UTC)
    trends = [_trend(1, "complete", 5, 10), _trend(2, "gap", 1, 0)]
    intelligence = {"unified_ranking": trends, "public_top10": trends}
    before = repr(intelligence)

    result = sync_enrichment_queue(intelligence, path=tmp_path / "queue.sqlite3", at=at)

    assert repr(intelligence) == before
    assert result["counts"] == {
        "company_ontology": {"pending": 1, "complete": 1},
        "related_keywords": {"pending": 1, "complete": 1},
        "trend_context": {"pending": 0, "complete": 2},
    }
    assert result["pending_total"] == 2
    assert result["required_evidence_count"] == {
        "trend_context": 1,
        "related_keywords": 5,
        "company_ontology": 10,
    }
    assert {item["task_kind"] for item in result["pending"]} == {
        "company_ontology", "related_keywords",
    }
    assert all(item["affects_score"] is False for item in result["pending"])
    assert all(item["representative_term"] == "gap" for item in result["pending"])
    contract = result["llm_research_contract"]
    assert contract["mode"] == "proposal_then_deterministic_review"
    assert contract["candidate_targets"] == {
        "trend_context": 8,
        "related_keywords": 15,
            "company_ontology": 30,
    }
    assert contract["llm_can_change_ranking"] is False
    assert contract["unverified_candidates_public"] is False
    company_task = next(
        item for item in result["pending"] if item["task_kind"] == "company_ontology"
    )
    assert "트렌드→사용 장면→장비·서비스→산업→기업" in company_task["llm_research_prompt"]
    assert company_task["evidence_policy"]["llm_role"] == "creative_graph_expansion_only"


def test_queue_is_idempotent_per_hour_and_keeps_history_across_hours(tmp_path):
    path = tmp_path / "queue.sqlite3"
    first_at = datetime(2026, 8, 13, tzinfo=UTC)
    first = {"unified_ranking": [_trend(1, "trend", 0, 0)], "public_top10": []}
    second = {"unified_ranking": [_trend(3, "trend", 5, 10)], "public_top10": []}

    sync_enrichment_queue(first, path=path, at=first_at)
    sync_enrichment_queue(first, path=path, at=first_at)
    result = sync_enrichment_queue(second, path=path, at=first_at + timedelta(hours=1))

    assert result["pending_total"] == 0
    assert result["tracked_observations"] == 6
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM enrichment_tasks").fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM enrichment_task_observations"
        ).fetchone()[0] == 6


def test_pending_output_only_contains_candidates_seen_in_current_hour(tmp_path):
    path = tmp_path / "queue.sqlite3"
    first_at = datetime(2026, 8, 13, tzinfo=UTC)
    sync_enrichment_queue(
        {"unified_ranking": [_trend(1, "old-gap")], "public_top10": []},
        path=path,
        at=first_at,
    )

    result = sync_enrichment_queue(
        {"unified_ranking": [_trend(2, "current-gap")], "public_top10": []},
        path=path,
        at=first_at + timedelta(hours=1),
    )

    assert {item["event_key"] for item in result["pending"]} == {"current-gap"}
    assert result["pending_total"] == 2


def test_ten_complete_companies_close_company_task(tmp_path):
    result = sync_enrichment_queue(
        {"unified_ranking": [_trend(1, "ready-company", 0, 10)], "public_top10": []},
        path=tmp_path / "queue.sqlite3",
        at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert result["counts"]["company_ontology"] == {"pending": 0, "complete": 1}
    assert result["counts"]["related_keywords"] == {"pending": 1, "complete": 0}


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


def test_existing_two_kind_queue_is_migrated_without_losing_history(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE enrichment_tasks (
                event_key TEXT NOT NULL,
                task_kind TEXT NOT NULL CHECK(task_kind IN ('related_keywords','company_ontology')),
                representative_term TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL, latest_rank INTEGER NOT NULL,
                latest_lane TEXT NOT NULL, priority INTEGER NOT NULL,
                current_count INTEGER NOT NULL, required_count INTEGER NOT NULL,
                missing_count INTEGER NOT NULL, status TEXT NOT NULL,
                observed_terms_json TEXT NOT NULL, evidence_policy_json TEXT NOT NULL,
                affects_score INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(event_key, task_kind)
            );
            CREATE TABLE enrichment_task_observations (
                event_key TEXT NOT NULL, task_kind TEXT NOT NULL,
                observed_at TEXT NOT NULL, rank INTEGER NOT NULL,
                current_count INTEGER NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY(event_key, task_kind, observed_at),
                FOREIGN KEY(event_key, task_kind)
                    REFERENCES enrichment_tasks(event_key, task_kind)
            );
            INSERT INTO enrichment_tasks VALUES
                ('legacy','related_keywords','legacy','2026-08-13T00:00:00+00:00',
                 '2026-08-13T00:00:00+00:00',1,'main',2999,0,5,5,'pending','[]','{}',0);
            INSERT INTO enrichment_task_observations VALUES
                ('legacy','related_keywords','2026-08-13T00:00:00+00:00',1,0,'pending');
            """
        )

    initialize_enrichment_queue(path)

    with sqlite3.connect(path) as connection:
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='enrichment_tasks'"
        ).fetchone()[0]
        assert "'trend_context'" in schema
        assert connection.execute("SELECT COUNT(*) FROM enrichment_tasks").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM enrichment_task_observations"
        ).fetchone()[0] == 1
