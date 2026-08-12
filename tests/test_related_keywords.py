import io
import json

from trzip.related_keywords import google_related_keywords, x_related_keywords


def test_x_related_keywords_returns_aggregates_without_raw_posts(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    payload = {"data": [
        {"text": "말복에는 삼계탕 보양식", "entities": {"hashtags": [{"tag": "삼계탕"}]}},
        {"text": "말복 외식 삼계탕 할인", "entities": {}},
    ]}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *args, **kwargs: Response(json.dumps(payload).encode("utf-8")))
    result = x_related_keywords("말복", candidates=["삼계탕", "보양식"])
    assert result["status"] == "observed"
    assert result["post_count"] == 2
    assert result["keywords"][0]["text"] in {"#삼계탕", "삼계탕"}
    assert "data" not in result and "posts" not in result


def test_event_vocabulary_blocks_unrelated_cooccurrence(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    payload = {"data": [
        {"text": "쿠우쿠우 뷔페 친일 증조부", "entities": {"hashtags": [{"tag": "드친소"}]}},
        {"text": "쿠우쿠우 뷔페 할인", "entities": {}},
    ]}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *args, **kwargs: Response(json.dumps(payload).encode("utf-8")))
    result = x_related_keywords("쿠우쿠우", candidates=["뷔페", "할인", "초밥"])
    assert [row["text"] for row in result["keywords"]] == ["뷔페"]
    assert all(row["text"] not in {"친일", "증조부", "#드친소"} for row in result["keywords"])


def test_single_hashtag_does_not_count_as_two_observations(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    payload = {"data": [
        {"text": "말복 #삼계탕", "entities": {"hashtags": [{"tag": "삼계탕"}]}},
        {"text": "말복 외식", "entities": {}},
    ]}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *args, **kwargs: Response(json.dumps(payload).encode("utf-8")))
    result = x_related_keywords("말복", candidates=["삼계탕"])
    assert result["status"] == "insufficient"
    assert result["keywords"] == []


def test_google_rss_requires_repetition_across_entries():
    result = google_related_keywords([
        {"title": "말복 삼계탕", "description": "보양식 예약"},
        {"title": "복날 외식", "description": "삼계탕 할인"},
    ], "말복", candidates=["삼계탕", "보양식"])
    assert result["status"] == "observed"
    assert result["keywords"] == [
        {"text": "삼계탕", "count": 2, "status": "observed_google_rss_repetition"}
    ]
