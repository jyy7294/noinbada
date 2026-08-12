import io
import json

from trzip.related_keywords import x_related_keywords


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


def test_empty_event_vocabulary_does_not_fall_back_to_arbitrary_feed_terms(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    payload = {"data": [
        {"text": "데이즈드 #NCTWISH 유우시 리쿠", "entities": {"hashtags": [{"tag": "NCTWISH"}]}},
        {"text": "데이즈드 #NCTWISH 사진", "entities": {"hashtags": [{"tag": "NCTWISH"}]}},
    ]}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *args, **kwargs: Response(json.dumps(payload).encode("utf-8")))
    result = x_related_keywords("데이즈드", candidates=[])

    assert result["keywords"] == []
    assert result["evidence_status"] == "insufficient"
