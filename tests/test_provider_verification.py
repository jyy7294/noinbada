import json
import sqlite3
from datetime import UTC, datetime

from trzip.provider_verification import (
    ProviderCredentials,
    ProviderRequestError,
    TransportResponse,
    TrendReference,
    collect_naver_context,
    collect_youtube_context,
    latest_verification_by_trend,
    mark_news_candidate_core_observed,
    persist_news_discovery,
    persist_verification_result,
    provider_readiness,
    read_news_discovery_queue,
    read_verification_ledger,
    resolve_provider_credentials,
    verify_terms,
    verification_trend_keys_at,
    youtube_search_attempts_on_kst_date,
)


NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def response(payload: dict, status: int = 200) -> TransportResponse:
    return TransportResponse(status=status, body=json.dumps(payload).encode("utf-8"))


class RoutingTransport:
    def __init__(self, routes: dict[str, list[object]]):
        self.routes = {key: list(value) for key, value in routes.items()}
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.bodies: list[bytes] = []

    def get(self, url, *, headers, timeout):
        self.urls.append(url)
        self.headers.append(headers)
        route = next(key for key in self.routes if key in url)
        item = self.routes[route].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, *, headers, body, timeout):
        self.urls.append(url)
        self.headers.append(headers)
        self.bodies.append(body)
        route = next(key for key in self.routes if key in url)
        item = self.routes[route].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_existing_windows_aliases_are_recognized_without_exposure():
    environment = {
        "KIWOOM_TRZIP_NAVER_CLIENT_ID": "naver-id-secret",
        "KIWOOM_TRZIP_NAVER_CLIENT_SECRET": "naver-secret-secret",
        "KIWOOM_TRZIP_YOUTUBE_API_KEY": "youtube-secret",
    }

    credentials = resolve_provider_credentials(environment)
    readiness = provider_readiness(environment)

    assert credentials.naver_client_id == "naver-id-secret"
    assert readiness["naver"]["status"] == "configured_unverified"
    assert readiness["youtube"]["status"] == "configured_unverified"
    assert readiness["instagram"]["status"] == "unavailable"
    assert all(row["ranking_effect"] == "none" for row in readiness.values())
    assert "secret" not in repr(credentials)
    assert "secret" not in json.dumps(readiness)


def test_youtube_api_key_aliases_and_instagram_mvp_state_are_explicit():
    credentials = resolve_provider_credentials(
        {
            "YOUTUBE_DATA_API_KEY": "youtube-alias-secret",
            "INSTAGRAM_ACCESS_TOKEN": "meta-secret",
        }
    )
    readiness = provider_readiness(
        {
            "YOUTUBE_DATA_API_KEY": "youtube-alias-secret",
            "INSTAGRAM_ACCESS_TOKEN": "meta-secret",
        }
    )

    assert credentials.youtube_api_key == "youtube-alias-secret"
    assert readiness["youtube"]["status"] == "configured_unverified"
    assert readiness["instagram"]["status"] == "unavailable"
    assert "not enabled" in readiness["instagram"]["reason"]
    assert "secret" not in json.dumps(readiness)


def test_naver_news_and_blog_are_context_evidence_with_retry_and_audit(tmp_path):
    transport = RoutingTransport(
        {
            "/news.json": [
                ProviderRequestError(
                    "temporary", status=503, body=b'{"errorCode":"SE03"}'
                ),
                response(
                    {
                        "total": 12,
                        "items": [
                            {
                                "title": "<b>말복</b> 앞두고 삼계탕 수요",
                                "originallink": "https://example.com/news/1",
                                "pubDate": "Wed, 12 Aug 2026 12:00:00 +0900",
                            }
                        ],
                    }
                ),
            ],
            "/blog.json": [
                response(
                    {
                        "total": 3,
                        "items": [
                            {
                                "title": "말복 메뉴 기록",
                                "link": "https://blog.example.com/1",
                                "postdate": "20260812",
                                "bloggername": "테스트 블로그",
                            }
                        ],
                    }
                )
            ],
        }
    )
    credentials = ProviderCredentials("id-value", "secret-value", "", "")
    reference = TrendReference("event:malbok", "말복")

    result = collect_naver_context(
        reference,
        at=NOW,
        credentials=credentials,
        transport=transport,
        sleeper=lambda _: None,
    )
    run_id = persist_verification_result(result, tmp_path / "ledger.sqlite3")

    assert run_id == 1
    assert result.status == "observed"
    assert len(result.evidence) == 2
    assert len(result.attempts) == 6
    assert result.attempts[0].retryable is True
    ledger = read_verification_ledger(tmp_path / "ledger.sqlite3")
    encoded = json.dumps(ledger, ensure_ascii=False)
    assert ledger[0]["ranking_effect"] == "none"
    assert ledger[0]["attempt_count"] == 6
    assert "id-value" not in encoded
    assert "secret-value" not in encoded


def test_naver_api_hub_collects_news_context_without_ranking_signal():
    transport = RoutingTransport({
        "/search/v1/news": [response({
            "total": 1,
            "items": [{
                "title": "두쫀쿠 확산",
                "originallink": "https://example.com/news/dubai-cookie",
                "pubDate": "Wed, 12 Aug 2026 20:00:00 +0900",
            }],
        })],
        "/search/v1/blog": [response({"total": 0, "items": []})],
        "/search-trend/v1/search": [response({
            "results": [{
                "title": "두쫀쿠",
                "data": [
                    {"period": "2026-08-11", "ratio": 20},
                    {"period": "2026-08-12", "ratio": 60},
                ],
            }],
        })],
    })
    result = collect_naver_context(
        TrendReference("event:dubai-cookie", "두쫀쿠"),
        at=NOW,
        credentials=ProviderCredentials(
            naver_client_id="hub-id",
            naver_client_secret="hub-secret",
            naver_api_hub=True,
        ),
        transport=transport,
        sleeper=lambda _: None,
    )

    assert result.status == "observed"
    assert "search_trend" not in result.metrics
    assert any("X-NCP-APIGW-API-KEY-ID" in headers for headers in transport.headers)
    assert transport.bodies == []


def test_youtube_uses_kr_context_marks_total_as_approximate_and_stores_stats(tmp_path):
    transport = RoutingTransport(
        {
            "/youtube/v3/search": [
                response(
                    {
                        "pageInfo": {"totalResults": 1234},
                        "items": [
                            {
                                "id": {"videoId": "video123"},
                                "snippet": {
                                    "title": "말복 삼계탕",
                                    "publishedAt": "2026-08-12T01:00:00Z",
                                    "channelTitle": "음식 채널",
                                },
                            }
                        ],
                    }
                )
            ],
            "/youtube/v3/videos": [
                response(
                    {
                        "items": [
                            {
                                "id": "video123",
                                "statistics": {
                                    "viewCount": "5000",
                                    "likeCount": "200",
                                    "commentCount": "10",
                                },
                            }
                        ]
                    }
                )
            ],
        }
    )
    credentials = ProviderCredentials("", "", "youtube-key-secret", "")

    result = collect_youtube_context(
        TrendReference("event:malbok", "말복"),
        at=NOW,
        credentials=credentials,
        transport=transport,
        sleeper=lambda _: None,
    )
    persist_verification_result(result, tmp_path / "ledger.sqlite3")

    search_url = transport.urls[0]
    assert "regionCode=KR" in search_url
    assert "relevanceLanguage=ko" in search_url
    assert result.metrics["search_total_is_approximate"] is True
    assert result.evidence[0].metrics["viewCount"] == 5000
    assert result.ranking_effect == "none"
    assert "youtube-key-secret" not in json.dumps(
        read_verification_ledger(tmp_path / "ledger.sqlite3"), ensure_ascii=False
    )


def test_youtube_quota_error_is_not_zero_or_no_match():
    transport = RoutingTransport(
        {
            "/youtube/v3/search": [
                ProviderRequestError(
                    "quota",
                    status=403,
                    body=json.dumps(
                        {
                            "error": {
                                "message": "quota exceeded",
                                "errors": [{"reason": "quotaExceeded"}],
                            }
                        }
                    ).encode("utf-8"),
                )
            ]
        }
    )

    result = collect_youtube_context(
        TrendReference("event:malbok", "말복"),
        at=NOW,
        credentials=ProviderCredentials("", "", "key", ""),
        transport=transport,
        sleeper=lambda _: None,
    )

    assert result.status == "quota_exhausted"
    assert result.matched is None
    assert result.error_code == "quotaExceeded"


def test_verify_terms_persists_unavailable_instead_of_fabricated_zero(tmp_path):
    target = tmp_path / "ledger.sqlite3"

    results = verify_terms(
        [TrendReference("event:malbok", "말복")],
        path=target,
        at=NOW,
        credentials=ProviderCredentials(),
        transport=RoutingTransport({}),
        sleeper=lambda _: None,
    )

    assert [row.status for row in results] == ["unavailable", "unavailable"]
    assert all(row.matched is None for row in results)
    assert all(row.metrics == {} for row in results)
    assert len(read_verification_ledger(target)) == 2


def test_verify_terms_does_not_activate_instagram_when_token_exists(tmp_path):
    target = tmp_path / "ledger.sqlite3"

    results = verify_terms(
        [TrendReference("event:malbok", "malbok")],
        path=target,
        at=NOW,
        credentials=ProviderCredentials("", "", "", "meta-token"),
        transport=RoutingTransport({}),
        sleeper=lambda _: None,
    )

    assert [row.provider for row in results] == ["naver", "youtube"]


def test_naver_auth_failure_opens_hourly_circuit_and_defers_remaining_terms(tmp_path):
    target = tmp_path / "ledger.sqlite3"
    auth_error = lambda: ProviderRequestError(
        "authentication failed",
        status=401,
        body=b'{"errorCode":"024","errorMessage":"Authentication failed"}',
    )
    transport = RoutingTransport(
        {
            "/news.json": [auth_error()],
            "/blog.json": [auth_error()],
        }
    )

    results = verify_terms(
        [TrendReference("event:one", "첫번째"), TrendReference("event:two", "두번째")],
        path=target,
        at=NOW,
        credentials=ProviderCredentials("id", "secret", "", ""),
        transport=transport,
        sleeper=lambda _: None,
    )

    naver = [row for row in results if row.provider == "naver"]
    assert [row.status for row in naver] == ["failed", "deferred"]
    assert naver[0].error_code == "024"
    assert len(transport.urls) == 1


def test_youtube_daily_budget_counts_attempts_not_runs(tmp_path):
    target = tmp_path / "ledger.sqlite3"
    transport = RoutingTransport(
        {
            "/youtube/v3/search": [
                ProviderRequestError("temporary", status=503),
                response({"pageInfo": {"totalResults": 0}, "items": []}),
            ]
        }
    )
    result = collect_youtube_context(
        TrendReference("event:malbok", "말복"),
        at=NOW,
        credentials=ProviderCredentials("", "", "key", ""),
        transport=transport,
        sleeper=lambda _: None,
    )
    persist_verification_result(result, target)

    # Quota is charged on the actual request date, not the fixed observation
    # fixture date. This keeps the test deterministic across a KST midnight.
    actual_request_time = datetime.fromisoformat(result.attempts[0].started_at)
    assert youtube_search_attempts_on_kst_date(target, actual_request_time) == 2


def test_news_only_term_stays_out_of_ranking_until_core_source_is_observed(tmp_path):
    target = tmp_path / "ledger.sqlite3"
    article = {
        "title": "제2의 버터떡, 양즈깐루 관심",
        "publisher": "서울경제",
        "url": "https://www.sedaily.com/article/20058091",
        "published_at": "2026-06-20T14:00:00+09:00",
        "retrieved_at": "2026-08-12T21:00:00+09:00",
        "observed_term": "양즈깐루",
        "claims": [{"type": "consumer_behavior", "text": "여름 디저트 관심"}],
        "review_status": "unreviewed",
    }

    persist_news_discovery([article], target)
    queue = read_news_discovery_queue(target)

    assert queue[0]["core_source_gate"] == "awaiting_x_or_google"
    assert queue[0]["ranking_eligible_from_news_alone"] is False
    assert queue[0]["ranking_insertion_performed"] is False

    mark_news_candidate_core_observed(
        path=target,
        observed_term="양즈깐루",
        source="google_trends",
        observed_at=NOW,
    )
    queue = read_news_discovery_queue(target)

    assert queue[0]["core_source_gate"] == "satisfied_by_x_or_google"
    assert queue[0]["ranking_insertion_performed"] is False
    assert queue[0]["ranking_eligible_from_news_alone"] is False


def test_provider_ledger_is_append_only_for_repeated_hourly_runs(tmp_path):
    target = tmp_path / "ledger.sqlite3"
    first = collect_youtube_context(
        TrendReference("event:malbok", "말복"),
        at=NOW,
        credentials=ProviderCredentials(),
        transport=RoutingTransport({}),
    )
    persist_verification_result(first, target)
    persist_verification_result(first, target)

    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM provider_verification_runs").fetchone()[0] == 2


def test_hourly_completed_term_requires_all_three_provider_states(tmp_path):
    target = tmp_path / "ledger.sqlite3"
    reference = TrendReference("event:malbok", "malbok")
    youtube = collect_youtube_context(
        reference,
        at=NOW,
        credentials=ProviderCredentials(),
        transport=RoutingTransport({}),
    )
    persist_verification_result(youtube, target)

    assert verification_trend_keys_at(target, NOW) == set()

    verify_terms(
        [reference],
        path=target,
        at=NOW,
        credentials=ProviderCredentials(),
        transport=RoutingTransport({}),
    )

    assert verification_trend_keys_at(target, NOW) == {"event:malbok"}


def test_frontend_safe_verification_block_has_no_ranking_score(tmp_path):
    target = tmp_path / "ledger.sqlite3"
    result = collect_youtube_context(
        TrendReference("event:malbok", "말복"),
        at=NOW,
        credentials=ProviderCredentials(),
        transport=RoutingTransport({}),
    )
    persist_verification_result(result, target)

    payload = latest_verification_by_trend(target)

    assert payload["event:malbok"]["ranking_effect"] == "none"
    assert "score" not in json.dumps(payload)
    assert payload["event:malbok"]["providers"]["youtube"]["status"] == "unavailable"
