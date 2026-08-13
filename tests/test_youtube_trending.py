import json
from datetime import UTC, datetime, timedelta

from trzip.provider_verification import ProviderCredentials, TransportResponse
from trzip.youtube_trending import collect_youtube_trending


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, *, headers, timeout):
        self.urls.append(url)
        return TransportResponse(200, json.dumps(self.payload).encode("utf-8"))


def _payload(order=("odyssey", "song")):
    rows = {
        "odyssey": {
            "id": "odyssey",
            "snippet": {
                "title": "The Odyssey | Official Trailer",
                "channelTitle": "Universal Pictures",
                "categoryId": "1",
                "publishedAt": "2026-07-01T00:00:00Z",
            },
            "statistics": {"viewCount": "12000000", "likeCount": "400000"},
        },
        "song": {
            "id": "song",
            "snippet": {
                "title": "테스트 노래 (Official MV)",
                "channelTitle": "Official Music",
                "categoryId": "10",
                "publishedAt": "2026-08-12T00:00:00Z",
            },
            "statistics": {"viewCount": "1000000", "likeCount": "50000"},
        },
    }
    return {"items": [rows[key] for key in order]}


def test_youtube_kr_chart_is_persisted_as_separate_content_lane(tmp_path, monkeypatch):
    monkeypatch.delenv("TRZIP_DISABLE_EXTERNAL_YOUTUBE_TRENDING", raising=False)
    at = datetime(2026, 8, 13, 6, tzinfo=UTC)
    transport = FakeTransport(_payload())

    result = collect_youtube_trending(
        path=tmp_path / "trzip.sqlite3",
        at=at,
        credentials=ProviderCredentials(youtube_api_key="not-exposed"),
        transport=transport,
    )

    assert result["status"] == "observed"
    assert result["top10"][0]["display_topic"] == "오디세이"
    assert result["top10"][0]["youtube_trend_rank"] == 1
    assert result["affects_x_google_rank"] is False
    assert "regionCode=KR" in transport.urls[0]
    assert "chart=mostPopular" in transport.urls[0]
    assert len(result["category_charts"]) == 4
    assert {row["category_id"] for row in result["category_charts"]} == {"1", "10", "20", "24"}
    assert all(row["status"] == "observed" for row in result["category_charts"])
    assert any("videoCategoryId=1" in url for url in transport.urls)
    assert "not-exposed" not in json.dumps(result, ensure_ascii=False)

    # Same hour is idempotent and does not call the provider again.
    again = collect_youtube_trending(
        path=tmp_path / "trzip.sqlite3",
        at=at,
        credentials=ProviderCredentials(youtube_api_key="not-exposed"),
        transport=FakeTransport({"items": []}),
    )
    assert again == result


def test_same_song_topic_and_official_mv_are_merged_without_losing_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("TRZIP_DISABLE_EXTERNAL_YOUTUBE_TRENDING", raising=False)
    payload = _payload()
    payload["items"].append({
        "id": "song-mv",
        "snippet": {
            "title": "Official Music - 테스트 노래 (Official MV)",
            "channelTitle": "Official Music",
            "categoryId": "10",
            "publishedAt": "2026-08-12T00:30:00Z",
        },
        "statistics": {"viewCount": "800000"},
    })
    result = collect_youtube_trending(
        path=tmp_path / "trzip.sqlite3",
        at=datetime(2026, 8, 13, 6, tzinfo=UTC),
        credentials=ProviderCredentials(youtube_api_key="key"),
        transport=FakeTransport(payload),
    )
    song = next(row for row in result["ranking"] if row["display_topic"] == "테스트 노래")
    assert song["supporting_video_count"] == 2
    assert len(song["source_evidence"]) == 2


def test_youtube_rank_change_compares_previous_observed_chart(tmp_path, monkeypatch):
    monkeypatch.delenv("TRZIP_DISABLE_EXTERNAL_YOUTUBE_TRENDING", raising=False)
    path = tmp_path / "trzip.sqlite3"
    first = datetime(2026, 8, 13, 5, tzinfo=UTC)
    collect_youtube_trending(
        path=path, at=first,
        credentials=ProviderCredentials(youtube_api_key="key"),
        transport=FakeTransport(_payload(("song", "odyssey"))),
    )
    result = collect_youtube_trending(
        path=path, at=first + timedelta(hours=1),
        credentials=ProviderCredentials(youtube_api_key="key"),
        transport=FakeTransport(_payload(("odyssey", "song"))),
    )
    moved_video = next(row for row in result["video_chart"] if row["video_id"] == "odyssey")
    assert moved_video["youtube_rank_change"] == 1
    assert moved_video["rank_change_status"] == "measured"
    assert result["top10"][0]["youtube_trend_rank_change"] == 1
    assert result["top10"][0]["rank_change_status"] == "measured"


def test_missing_key_is_explicit_and_not_a_zero_chart(tmp_path, monkeypatch):
    monkeypatch.delenv("TRZIP_DISABLE_EXTERNAL_YOUTUBE_TRENDING", raising=False)
    result = collect_youtube_trending(
        path=tmp_path / "trzip.sqlite3",
        at=datetime(2026, 8, 13, 6, tzinfo=UTC),
        credentials=ProviderCredentials(),
    )
    assert result["status"] == "unavailable"
    assert result["error_code"] == "api_key_not_configured"
    assert result["ranking"] == []
    assert result["category_charts"] == []
