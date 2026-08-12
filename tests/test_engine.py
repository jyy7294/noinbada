import pytest

from trzip.engine import rank_topics
from trzip.models import Keyword, Source, TopicObservation
from trzip.hourly_store import backfill, collect_current, coverage, snapshot


def topic(**overrides):
    values = dict(topic_id="a", name="테스트", category="food", form="product", x_rank=1,
                  google_rank=2, momentum=.8, persistence_days=7)
    values.update(overrides)
    return TopicObservation(**values)


def test_only_main_is_limited_but_other_candidates_are_preserved():
    topics = [topic(topic_id=str(i), name=f"주제{i}") for i in range(12)]
    topics += [topic(topic_id="issue", category="society", policy_tags=("breaking_news",))]
    topics += [topic(topic_id="review", category="other", policy_tags=("generic_noun",))]
    result = rank_topics(topics)
    assert len(result["main"]) == 10
    assert [x.observation.topic_id for x in result["issue"]] == ["issue"]
    assert [x.observation.topic_id for x in result["review"]] == ["review"]


def test_single_source_topic_is_visible_with_lower_cross_source_score():
    result = rank_topics([topic(topic_id="both"), topic(topic_id="x", google_rank=None)])
    assert len(result["main"]) == 2
    assert result["main"][0].observation.topic_id == "both"
    assert result["main"][1].cross_source_score == 0


def test_invalid_keyword_source_cannot_enter_engine():
    with pytest.raises((TypeError, ValueError)):
        Keyword("오염", "youtube", "invalid")


def test_hourly_backfill_covers_may_through_current_hour(tmp_path):
    target = tmp_path / "hourly.sqlite3"
    from datetime import UTC, datetime
    count = backfill(datetime(2026, 5, 2, 0, tzinfo=UTC), target)
    # Backfill begins at 2026-05-01 00:00 KST (2026-04-30 15:00 UTC).
    assert count == 34 * 20
    stats = coverage(target)
    assert stats["hours"] == 34
    assert stats["observed_rows"] == 0
    assert stats["generated_rows"] == count
    assert {row["provenance"] for row in snapshot(datetime(2026, 5, 1, tzinfo=UTC), target)} == {"generated"}


def test_current_collection_falls_back_without_disguising_generated_data(tmp_path, monkeypatch):
    target = tmp_path / "hourly.sqlite3"
    monkeypatch.setenv("TRZIP_DISABLE_USER_SECRET_BRIDGE", "1")
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.setattr("trzip.hourly_store.collect_google", lambda at: [])
    from datetime import UTC, datetime
    result = collect_current(target, datetime(2026, 6, 15, tzinfo=UTC))
    assert result["observed"] == 0
    assert result["generated"] == 20
    assert result["trends_mcp_used"] is False
    assert coverage(target)["generated_rows"] == 20


def test_scheduled_collection_keeps_mcp_disabled_when_key_exists(tmp_path, monkeypatch):
    target = tmp_path / "hourly.sqlite3"
    monkeypatch.setenv("TRENDS_MCP_API_KEY", "not-called")
    monkeypatch.setattr("trzip.hourly_store.collect_google", lambda at: [])
    calls = []
    monkeypatch.setattr("trzip.hourly_store.collect_trends_mcp",
                        lambda *args, **kwargs: calls.append(args) or [])
    from datetime import UTC, datetime
    result = collect_current(target, datetime(2026, 6, 15, tzinfo=UTC))
    assert result["trends_mcp_used"] is False
    assert result["audit"]["google_trends_mcp"]["status"] == "disabled"
    assert calls == []
