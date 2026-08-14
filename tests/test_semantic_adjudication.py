from datetime import UTC, datetime

from trzip.semantic_adjudication import run_semantic_adjudication


def _item(*, lane: str = "review") -> dict:
    return {
        "event_key": "polestar-3",
        "display_name": "Polestar 3",
        "raw_terms": ["Polestar 3"],
        "lane": lane,
        "broad_category": "other",
        "latest_source_ranks": {"google_trends": 4},
        "score": 61.0,
        "context_research": {
            "status": "ready",
            "trigger_title": "Polestar 3 launch update",
            "why_now": "A verified current news article explains the observed interest.",
            "evidence_urls": ["https://example.com/news/polestar-3"],
        },
    }


def test_semantic_review_can_promote_only_grounded_non_issue(tmp_path, monkeypatch):
    monkeypatch.setenv("TRZIP_SEMANTIC_LLM_URL", "https://example.invalid/v1/chat")
    monkeypatch.setenv("TRZIP_SEMANTIC_LLM_API_KEY", "test")
    monkeypatch.setenv("TRZIP_SEMANTIC_LLM_MODEL", "test-model")
    intelligence = {"unified_ranking": [_item()]}

    def transport(_url, _payload, _headers):
        return {"choices": [{"message": {"content": """{
          \"decision\": \"approve\", \"broad_category\": \"consumer\",
          \"confidence\": 0.91,
          \"reason\": \"The cited launch article resolves the concrete vehicle model context.\",
          \"evidence_urls\": [\"https://example.com/news/polestar-3\"]
        }"""}}]}

    run_semantic_adjudication(
        intelligence,
        path=tmp_path / "semantic.sqlite3",
        at=datetime(2026, 8, 14, tzinfo=UTC),
        transport=transport,
    )

    item = intelligence["unified_ranking"][0]
    assert item["lane"] == "main"
    assert item["broad_category"] == "consumer"
    assert item["semantic_adjudication_effect"] == "promoted_or_confirmed_main"
    assert item["latest_source_ranks"] == {"google_trends": 4}
    assert item["score"] == 61.0


def test_semantic_review_cannot_promote_hard_issue_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("TRZIP_SEMANTIC_LLM_URL", "https://example.invalid/v1/chat")
    monkeypatch.setenv("TRZIP_SEMANTIC_LLM_API_KEY", "test")
    monkeypatch.setenv("TRZIP_SEMANTIC_LLM_MODEL", "test-model")
    intelligence = {"unified_ranking": [_item(lane="issue")]}

    def transport(_url, _payload, _headers):
        return {"choices": [{"message": {"content": """{
          \"decision\": \"approve\", \"broad_category\": \"consumer\",
          \"confidence\": 0.99,
          \"reason\": \"This response must never bypass the hard safety lane.\",
          \"evidence_urls\": [\"https://example.com/news/polestar-3\"]
        }"""}}]}

    run_semantic_adjudication(
        intelligence,
        path=tmp_path / "semantic.sqlite3",
        at=datetime(2026, 8, 14, tzinfo=UTC),
        transport=transport,
    )

    item = intelligence["unified_ranking"][0]
    assert item["lane"] == "issue"
    assert item["semantic_adjudication_effect"] == "hard_issue_lane_preserved"
