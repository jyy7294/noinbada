from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

from .news_evidence import validate_news_evidence


RANKING_EFFECT = "none"
NAVER_NEWS_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
NAVER_BLOG_ENDPOINT = "https://openapi.naver.com/v1/search/blog.json"
YOUTUBE_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
PROVIDER_DOCUMENTATION = {
    "naver": "https://developers.naver.com/docs/serviceapi/search/news",
    "youtube_search": "https://developers.google.com/youtube/v3/docs/search/list",
    "youtube_videos": "https://developers.google.com/youtube/v3/docs/videos/list",
}
KST = timedelta(hours=9)
DEFAULT_YOUTUBE_DAILY_SEARCH_BUDGET = 96


@dataclass(frozen=True)
class ProviderCredentials:
    naver_client_id: str = field(default="", repr=False)
    naver_client_secret: str = field(default="", repr=False)
    youtube_api_key: str = field(default="", repr=False)
    instagram_access_token: str = field(default="", repr=False)


@dataclass(frozen=True)
class TrendReference:
    trend_key: str
    representative_term: str


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


class JsonTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> TransportResponse: ...


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: bytes = b"",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class UrllibJsonTransport:
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> TransportResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return TransportResponse(
                    status=int(response.status),
                    body=response.read(),
                    headers={str(k): str(v) for k, v in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            raise ProviderRequestError(
                f"provider returned HTTP {exc.code}",
                status=int(exc.code),
                body=exc.read(),
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderRequestError("provider network request failed") from exc


@dataclass(frozen=True)
class RequestAttempt:
    attempt_no: int
    started_at: str
    finished_at: str
    status: str
    http_status: int | None
    error_code: str | None
    retryable: bool
    quota_bucket: str | None
    quota_cost: int


@dataclass(frozen=True)
class EvidenceItem:
    item_type: str
    provider_item_id: str
    title: str
    url: str
    published_at: str | None
    publisher: str | None
    metrics: dict
    provenance: dict


@dataclass(frozen=True)
class ProviderVerificationResult:
    observed_at: str
    trend_key: str
    representative_term: str
    provider: str
    status: str
    matched: bool | None
    endpoint: str | None
    attempts: tuple[RequestAttempt, ...]
    evidence: tuple[EvidenceItem, ...]
    metrics: dict
    error_code: str | None
    error_detail: str | None
    provenance: dict
    ranking_effect: str = RANKING_EFFECT


def _windows_user_environment(names: set[str]) -> dict[str, str]:
    if os.name != "nt" or not names:
        return {}
    try:
        import winreg

        values: dict[str, str] = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
            for name in names:
                try:
                    value, _ = winreg.QueryValueEx(registry, name)
                except FileNotFoundError:
                    continue
                if isinstance(value, str) and value.strip():
                    values[name] = value.strip()
        return values
    except OSError:
        return {}


def resolve_provider_credentials(
    environment: dict[str, str] | None = None,
) -> ProviderCredentials:
    """Resolve standard names and existing TRZIP aliases without logging values."""

    source = dict(environment) if environment is not None else dict(os.environ)
    known_names = {
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
        "YOUTUBE_API_KEY",
        "INSTAGRAM_ACCESS_TOKEN",
        "KIWOOM_TRZIP_NAVER_CLIENT_ID",
        "KIWOOM_TRZIP_NAVER_CLIENT_SECRET",
        "KIWOOM_TRZIP_YOUTUBE_API_KEY",
        "KIWOOM_TRZIP_INSTAGRAM_ACCESS_TOKEN",
    }
    if environment is None:
        for name, value in _windows_user_environment(known_names).items():
            source.setdefault(name, value)

    def first(*names: str) -> str:
        for name in names:
            value = str(source.get(name, "")).strip()
            if value:
                return value
        return ""

    return ProviderCredentials(
        naver_client_id=first("NAVER_CLIENT_ID", "KIWOOM_TRZIP_NAVER_CLIENT_ID"),
        naver_client_secret=first(
            "NAVER_CLIENT_SECRET", "KIWOOM_TRZIP_NAVER_CLIENT_SECRET"
        ),
        youtube_api_key=first("YOUTUBE_API_KEY", "KIWOOM_TRZIP_YOUTUBE_API_KEY"),
        instagram_access_token=first(
            "INSTAGRAM_ACCESS_TOKEN", "KIWOOM_TRZIP_INSTAGRAM_ACCESS_TOKEN"
        ),
    )


def provider_readiness(environment: dict[str, str] | None = None) -> dict[str, dict]:
    credentials = resolve_provider_credentials(environment)
    return {
        "naver": {
            "status": "configured_unverified"
            if credentials.naver_client_id and credentials.naver_client_secret
            else "unavailable",
            "role": "context_and_verification_only",
            "ranking_effect": RANKING_EFFECT,
        },
        "youtube": {
            "status": "configured_unverified"
            if credentials.youtube_api_key
            else "unavailable",
            "role": "context_and_verification_only",
            "ranking_effect": RANKING_EFFECT,
            "daily_search_budget": DEFAULT_YOUTUBE_DAILY_SEARCH_BUDGET,
        },
        "instagram": {
            "status": "configured_unverified"
            if credentials.instagram_access_token
            else "unavailable",
            "role": "context_and_verification_only",
            "ranking_effect": RANKING_EFFECT,
            "reason": None
            if credentials.instagram_access_token
            else "authorized Meta/Instagram access token is not configured",
        },
    }


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return current.astimezone(UTC).isoformat()


def _term(value: str) -> str:
    cleaned = " ".join(str(value).split())
    if not cleaned:
        raise ValueError("representative_term is required")
    return cleaned


def _strip_markup(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return " ".join(text.split())


def _safe_public_url(value: object) -> str:
    raw = str(value or "").strip()
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return raw


def _redact(value: str | None, secrets: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted[:500]


def _provider_error(body: bytes, status: int | None) -> tuple[str, str]:
    code = f"http_{status}" if status else "network_error"
    detail = "provider request failed"
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        if isinstance(payload, dict):
            if isinstance(payload.get("error"), dict):
                error = payload["error"]
                detail = str(error.get("message") or detail)
                errors = error.get("errors")
                if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                    code = str(errors[0].get("reason") or code)
            else:
                code = str(payload.get("errorCode") or payload.get("code") or code)
                detail = str(payload.get("errorMessage") or payload.get("message") or detail)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return code[:100], detail[:500]


def _request_json(
    *,
    endpoint: str,
    url: str,
    headers: dict[str, str],
    transport: JsonTransport,
    secrets: tuple[str, ...],
    quota_bucket: str | None,
    quota_cost: int,
    max_attempts: int,
    timeout: float,
    sleeper: Callable[[float], None],
) -> tuple[dict | None, tuple[RequestAttempt, ...], str | None, str | None]:
    attempts: list[RequestAttempt] = []
    last_code: str | None = None
    last_detail: str | None = None
    for attempt_no in range(1, max(1, max_attempts) + 1):
        started = _iso()
        try:
            response = transport.get(url, headers=headers, timeout=timeout)
            if response.status < 200 or response.status >= 300:
                raise ProviderRequestError(
                    f"provider returned HTTP {response.status}",
                    status=response.status,
                    body=response.body,
                )
            try:
                payload = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderRequestError(
                    "provider returned invalid JSON", status=response.status
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderRequestError(
                    "provider returned a non-object JSON payload", status=response.status
                )
            attempts.append(
                RequestAttempt(
                    attempt_no=attempt_no,
                    started_at=started,
                    finished_at=_iso(),
                    status="success",
                    http_status=response.status,
                    error_code=None,
                    retryable=False,
                    quota_bucket=quota_bucket,
                    quota_cost=quota_cost,
                )
            )
            return payload, tuple(attempts), None, None
        except ProviderRequestError as exc:
            code, detail = _provider_error(exc.body, exc.status)
            retryable = exc.status in {408, 429} or bool(exc.status and exc.status >= 500)
            if code in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
                retryable = False
            last_code = code
            last_detail = _redact(detail, secrets)
            attempts.append(
                RequestAttempt(
                    attempt_no=attempt_no,
                    started_at=started,
                    finished_at=_iso(),
                    status="failed",
                    http_status=exc.status,
                    error_code=code,
                    retryable=retryable,
                    quota_bucket=quota_bucket,
                    quota_cost=quota_cost,
                )
            )
            if not retryable or attempt_no >= max_attempts:
                break
            sleeper(min(2 ** (attempt_no - 1), 4))
        except Exception as exc:  # keep a scheduler alive on unexpected transport failures
            last_code = "transport_error"
            last_detail = _redact(str(exc) or "transport failed", secrets)
            attempts.append(
                RequestAttempt(
                    attempt_no=attempt_no,
                    started_at=started,
                    finished_at=_iso(),
                    status="failed",
                    http_status=None,
                    error_code=last_code,
                    retryable=True,
                    quota_bucket=quota_bucket,
                    quota_cost=quota_cost,
                )
            )
            if attempt_no >= max_attempts:
                break
            sleeper(min(2 ** (attempt_no - 1), 4))
    return None, tuple(attempts), last_code, last_detail


def _unavailable(
    reference: TrendReference,
    provider: str,
    at: datetime,
    reason: str,
) -> ProviderVerificationResult:
    return ProviderVerificationResult(
        observed_at=_iso(at),
        trend_key=reference.trend_key,
        representative_term=_term(reference.representative_term),
        provider=provider,
        status="unavailable",
        matched=None,
        endpoint=None,
        attempts=(),
        evidence=(),
        metrics={},
        error_code="not_configured",
        error_detail=reason,
        provenance={"role": "verification_only", "ranking_effect": RANKING_EFFECT},
    )


def deferred_result(
    reference: TrendReference,
    provider: str,
    at: datetime,
    reason: str,
) -> ProviderVerificationResult:
    return ProviderVerificationResult(
        observed_at=_iso(at),
        trend_key=reference.trend_key,
        representative_term=_term(reference.representative_term),
        provider=provider,
        status="deferred",
        matched=None,
        endpoint=None,
        attempts=(),
        evidence=(),
        metrics={},
        error_code="verification_budget_policy",
        error_detail=reason,
        provenance={"role": "verification_only", "ranking_effect": RANKING_EFFECT},
    )


def collect_naver_context(
    reference: TrendReference,
    *,
    at: datetime,
    credentials: ProviderCredentials,
    transport: JsonTransport | None = None,
    max_results_per_kind: int = 10,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
) -> ProviderVerificationResult:
    term = _term(reference.representative_term)
    if not credentials.naver_client_id or not credentials.naver_client_secret:
        return _unavailable(
            reference, "naver", at, "NAVER Search API credentials are not configured"
        )
    client = transport or UrllibJsonTransport()
    headers = {
        "Accept": "application/json",
        "X-Naver-Client-Id": credentials.naver_client_id,
        "X-Naver-Client-Secret": credentials.naver_client_secret,
        "User-Agent": "TRZIP/1.0 verification-only",
    }
    evidence: list[EvidenceItem] = []
    attempts: list[RequestAttempt] = []
    totals: dict[str, int] = {}
    errors: list[tuple[str, str]] = []
    for kind, endpoint in (("news", NAVER_NEWS_ENDPOINT), ("blog", NAVER_BLOG_ENDPOINT)):
        query = urllib.parse.urlencode(
            {"query": term, "display": max(1, min(max_results_per_kind, 100)), "sort": "date"}
        )
        payload, request_attempts, error_code, error_detail = _request_json(
            endpoint=endpoint,
            url=f"{endpoint}?{query}",
            headers=headers,
            transport=client,
            secrets=(credentials.naver_client_id, credentials.naver_client_secret),
            quota_bucket="naver_search",
            quota_cost=1,
            max_attempts=max_attempts,
            timeout=15,
            sleeper=sleeper,
        )
        offset = len(attempts)
        attempts.extend(
            RequestAttempt(**{**item.__dict__, "attempt_no": offset + item.attempt_no})
            for item in request_attempts
        )
        if payload is None:
            errors.append((error_code or "provider_error", error_detail or "request failed"))
            continue
        totals[kind] = max(0, int(payload.get("total") or 0))
        for index, item in enumerate(payload.get("items") or []):
            if not isinstance(item, dict):
                continue
            title = _strip_markup(item.get("title"))
            if not title:
                continue
            link = _safe_public_url(item.get("originallink") or item.get("link"))
            if not link:
                continue
            item_id = hashlib.sha256(f"{kind}|{link}".encode("utf-8")).hexdigest()[:24]
            evidence.append(
                EvidenceItem(
                    item_type=f"naver_{kind}",
                    provider_item_id=item_id,
                    title=title,
                    url=link,
                    published_at=str(item.get("pubDate") or item.get("postdate") or "") or None,
                    publisher=_strip_markup(item.get("bloggername")) or None,
                    metrics={"result_position": index + 1},
                    provenance={
                        "provider": "naver",
                        "endpoint": endpoint,
                        "query_term": term,
                        "sort": "date",
                        "documentation": PROVIDER_DOCUMENTATION["naver"],
                        "ranking_effect": RANKING_EFFECT,
                    },
                )
            )
    if evidence:
        status, matched = "observed", True
        error_code = error_detail = None
    elif errors and len(errors) == 2:
        status, matched = "failed", None
        error_code, error_detail = errors[-1]
    else:
        status, matched = "no_match", False
        error_code = error_detail = None
    return ProviderVerificationResult(
        observed_at=_iso(at),
        trend_key=reference.trend_key,
        representative_term=term,
        provider="naver",
        status=status,
        matched=matched,
        endpoint="naver_news_and_blog_search",
        attempts=tuple(attempts),
        evidence=tuple(evidence),
        metrics={
            "news_total_reported": totals.get("news"),
            "blog_total_reported": totals.get("blog"),
            "stored_evidence_count": len(evidence),
            "partial_provider_error_count": len(errors),
        },
        error_code=error_code,
        error_detail=error_detail,
        provenance={
            "provider": "NAVER Search API",
            "role": "news_blog_context_and_verification",
            "documentation": PROVIDER_DOCUMENTATION["naver"],
            "ranking_effect": RANKING_EFFECT,
        },
    )


def collect_youtube_context(
    reference: TrendReference,
    *,
    at: datetime,
    credentials: ProviderCredentials,
    transport: JsonTransport | None = None,
    published_within_days: int = 14,
    max_results: int = 5,
    max_search_attempts: int = 2,
    sleeper: Callable[[float], None] = time.sleep,
) -> ProviderVerificationResult:
    term = _term(reference.representative_term)
    if not credentials.youtube_api_key:
        return _unavailable(
            reference, "youtube", at, "YouTube Data API key is not configured"
        )
    client = transport or UrllibJsonTransport()
    published_after = (at.astimezone(UTC) - timedelta(days=max(1, published_within_days))).isoformat().replace(
        "+00:00", "Z"
    )
    search_params = {
        "part": "snippet",
        "type": "video",
        "q": term,
        "regionCode": "KR",
        "relevanceLanguage": "ko",
        "safeSearch": "moderate",
        "order": "relevance",
        "publishedAfter": published_after,
        "maxResults": max(1, min(max_results, 50)),
        "key": credentials.youtube_api_key,
    }
    payload, attempts, error_code, error_detail = _request_json(
        endpoint=YOUTUBE_SEARCH_ENDPOINT,
        url=f"{YOUTUBE_SEARCH_ENDPOINT}?{urllib.parse.urlencode(search_params)}",
        headers={"Accept": "application/json", "User-Agent": "TRZIP/1.0 verification-only"},
        transport=client,
        secrets=(credentials.youtube_api_key,),
        quota_bucket="youtube_search_queries",
        quota_cost=1,
        max_attempts=max_search_attempts,
        timeout=15,
        sleeper=sleeper,
    )
    if payload is None:
        status = "quota_exhausted" if error_code in {"quotaExceeded", "dailyLimitExceeded"} else "failed"
        return ProviderVerificationResult(
            observed_at=_iso(at),
            trend_key=reference.trend_key,
            representative_term=term,
            provider="youtube",
            status=status,
            matched=None,
            endpoint="youtube_search",
            attempts=attempts,
            evidence=(),
            metrics={},
            error_code=error_code,
            error_detail=error_detail,
            provenance={
                "provider": "YouTube Data API v3",
                "role": "video_context_and_verification",
                "documentation": PROVIDER_DOCUMENTATION["youtube_search"],
                "ranking_effect": RANKING_EFFECT,
            },
        )
    raw_items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    video_ids = [
        str((item.get("id") or {}).get("videoId") or "").strip()
        for item in raw_items
    ]
    video_ids = [item for item in video_ids if item]
    statistics: dict[str, dict] = {}
    all_attempts = list(attempts)
    secondary_error_count = 0
    if video_ids:
        video_params = {
            "part": "statistics",
            "id": ",".join(video_ids),
            "key": credentials.youtube_api_key,
        }
        detail_payload, detail_attempts, _, _ = _request_json(
            endpoint=YOUTUBE_VIDEOS_ENDPOINT,
            url=f"{YOUTUBE_VIDEOS_ENDPOINT}?{urllib.parse.urlencode(video_params)}",
            headers={"Accept": "application/json", "User-Agent": "TRZIP/1.0 verification-only"},
            transport=client,
            secrets=(credentials.youtube_api_key,),
            quota_bucket="youtube_data",
            quota_cost=1,
            max_attempts=2,
            timeout=15,
            sleeper=sleeper,
        )
        offset = len(all_attempts)
        all_attempts.extend(
            RequestAttempt(**{**item.__dict__, "attempt_no": offset + item.attempt_no})
            for item in detail_attempts
        )
        if detail_payload is None:
            secondary_error_count = 1
        else:
            for item in detail_payload.get("items") or []:
                if isinstance(item, dict) and item.get("id"):
                    statistics[str(item["id"])] = dict(item.get("statistics") or {})
    evidence: list[EvidenceItem] = []
    for item in raw_items:
        video_id = str((item.get("id") or {}).get("videoId") or "").strip()
        snippet = item.get("snippet") or {}
        if not video_id or not isinstance(snippet, dict):
            continue
        title = _strip_markup(snippet.get("title"))
        if not title:
            continue
        raw_stats = statistics.get(video_id, {})
        metrics = {
            key: int(raw_stats[key])
            for key in ("viewCount", "likeCount", "commentCount")
            if str(raw_stats.get(key, "")).isdigit()
        }
        evidence.append(
            EvidenceItem(
                item_type="youtube_video",
                provider_item_id=video_id,
                title=title,
                url=f"https://www.youtube.com/watch?v={urllib.parse.quote(video_id)}",
                published_at=str(snippet.get("publishedAt") or "") or None,
                publisher=_strip_markup(snippet.get("channelTitle")) or None,
                metrics=metrics,
                provenance={
                    "provider": "YouTube Data API v3",
                    "query_term": term,
                    "region_code": "KR",
                    "relevance_language": "ko",
                    "published_after": published_after,
                    "documentation": PROVIDER_DOCUMENTATION["youtube_search"],
                    "ranking_effect": RANKING_EFFECT,
                },
            )
        )
    page_info = payload.get("pageInfo") if isinstance(payload.get("pageInfo"), dict) else {}
    approximate_total = page_info.get("totalResults")
    return ProviderVerificationResult(
        observed_at=_iso(at),
        trend_key=reference.trend_key,
        representative_term=term,
        provider="youtube",
        status="observed" if evidence else "no_match",
        matched=True if evidence else False,
        endpoint="youtube_search_and_videos",
        attempts=tuple(all_attempts),
        evidence=tuple(evidence),
        metrics={
            "approximate_total_results": int(approximate_total)
            if str(approximate_total or "").isdigit()
            else None,
            "stored_evidence_count": len(evidence),
            "statistics_request_error_count": secondary_error_count,
            "search_total_is_approximate": True,
        },
        error_code=None,
        error_detail=None,
        provenance={
            "provider": "YouTube Data API v3",
            "role": "video_context_and_verification",
            "documentation": [
                PROVIDER_DOCUMENTATION["youtube_search"],
                PROVIDER_DOCUMENTATION["youtube_videos"],
            ],
            "ranking_effect": RANKING_EFFECT,
        },
    )


def initialize_verification_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS provider_verification_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at TEXT NOT NULL,
                trend_key TEXT NOT NULL,
                representative_term TEXT NOT NULL,
                provider TEXT NOT NULL CHECK(provider IN ('naver','youtube','instagram')),
                status TEXT NOT NULL CHECK(status IN (
                    'observed','no_match','unavailable','failed','quota_exhausted','deferred'
                )),
                matched INTEGER,
                endpoint TEXT,
                attempt_count INTEGER NOT NULL,
                error_code TEXT,
                error_detail TEXT,
                metrics_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                ranking_effect TEXT NOT NULL CHECK(ranking_effect='none'),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS provider_verification_runs_lookup
              ON provider_verification_runs(observed_at, trend_key, provider);
            CREATE TABLE IF NOT EXISTS provider_verification_attempts (
                run_id INTEGER NOT NULL REFERENCES provider_verification_runs(id),
                attempt_no INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                status TEXT NOT NULL,
                http_status INTEGER,
                error_code TEXT,
                retryable INTEGER NOT NULL,
                quota_bucket TEXT,
                quota_cost INTEGER NOT NULL,
                PRIMARY KEY (run_id, attempt_no)
            );
            CREATE INDEX IF NOT EXISTS provider_attempts_daily_quota
              ON provider_verification_attempts(started_at, quota_bucket);
            CREATE TABLE IF NOT EXISTS provider_evidence_items (
                run_id INTEGER NOT NULL REFERENCES provider_verification_runs(id),
                item_order INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                provider_item_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT,
                publisher TEXT,
                metrics_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                PRIMARY KEY (run_id, item_order)
            );
            CREATE TABLE IF NOT EXISTS news_discovery_candidates (
                candidate_key TEXT PRIMARY KEY,
                observed_term TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                article_count INTEGER NOT NULL DEFAULT 0,
                core_source_gate TEXT NOT NULL DEFAULT 'awaiting_x_or_google',
                ranking_insertion_performed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS news_discovery_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_key TEXT NOT NULL REFERENCES news_discovery_candidates(candidate_key),
                title TEXT NOT NULL,
                publisher TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                claims_json TEXT NOT NULL,
                review_status TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                UNIQUE(candidate_key, url)
            );
            CREATE TABLE IF NOT EXISTS news_core_observation_links (
                candidate_key TEXT NOT NULL REFERENCES news_discovery_candidates(candidate_key),
                source TEXT NOT NULL CHECK(source IN ('x','google_trends')),
                observed_at TEXT NOT NULL,
                PRIMARY KEY(candidate_key, source, observed_at)
            );
            """
        )


def persist_verification_result(result: ProviderVerificationResult, path: Path) -> int:
    if result.ranking_effect != RANKING_EFFECT:
        raise ValueError("verification data must never affect ranking")
    initialize_verification_ledger(path)
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """INSERT INTO provider_verification_runs
               (observed_at,trend_key,representative_term,provider,status,matched,endpoint,
                attempt_count,error_code,error_detail,metrics_json,provenance_json,
                ranking_effect,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result.observed_at,
                result.trend_key,
                result.representative_term,
                result.provider,
                result.status,
                None if result.matched is None else int(result.matched),
                result.endpoint,
                len(result.attempts),
                result.error_code,
                result.error_detail,
                json.dumps(result.metrics, ensure_ascii=False, sort_keys=True),
                json.dumps(result.provenance, ensure_ascii=False, sort_keys=True),
                result.ranking_effect,
                _iso(),
            ),
        )
        run_id = int(cursor.lastrowid)
        connection.executemany(
            """INSERT INTO provider_verification_attempts
               (run_id,attempt_no,started_at,finished_at,status,http_status,error_code,
                retryable,quota_bucket,quota_cost)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id,
                    row.attempt_no,
                    row.started_at,
                    row.finished_at,
                    row.status,
                    row.http_status,
                    row.error_code,
                    int(row.retryable),
                    row.quota_bucket,
                    row.quota_cost,
                )
                for row in result.attempts
            ],
        )
        connection.executemany(
            """INSERT INTO provider_evidence_items
               (run_id,item_order,item_type,provider_item_id,title,url,published_at,
                publisher,metrics_json,provenance_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id,
                    index,
                    row.item_type,
                    row.provider_item_id,
                    row.title,
                    row.url,
                    row.published_at,
                    row.publisher,
                    json.dumps(row.metrics, ensure_ascii=False, sort_keys=True),
                    json.dumps(row.provenance, ensure_ascii=False, sort_keys=True),
                )
                for index, row in enumerate(result.evidence, start=1)
            ],
        )
    return run_id


def youtube_search_attempts_on_kst_date(path: Path, at: datetime) -> int:
    initialize_verification_ledger(path)
    # The service is Korea-only, so quota accounting follows KST regardless of host locale.
    date_text = (at.astimezone(UTC) + KST).date().isoformat()
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """SELECT COALESCE(COUNT(*),0)
               FROM provider_verification_attempts
               WHERE quota_bucket='youtube_search_queries'
                 AND date(started_at, '+9 hours')=?""",
            (date_text,),
        ).fetchone()
    return int(row[0])


def verify_terms(
    references: list[TrendReference],
    *,
    path: Path,
    at: datetime,
    credentials: ProviderCredentials | None = None,
    transport: JsonTransport | None = None,
    naver_term_limit: int = 20,
    youtube_term_limit: int = 3,
    youtube_daily_search_budget: int = DEFAULT_YOUTUBE_DAILY_SEARCH_BUDGET,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[ProviderVerificationResult]:
    """Verify a bounded set while leaving X+Google ranking completely untouched."""

    resolved = credentials or resolve_provider_credentials()
    output: list[ProviderVerificationResult] = []
    naver_auth_blocked = False
    for index, reference in enumerate(references):
        if naver_auth_blocked:
            naver = deferred_result(
                reference,
                "naver",
                at,
                "NAVER authentication failed earlier in this hourly verification run",
            )
        elif index < naver_term_limit:
            naver = collect_naver_context(
                reference,
                at=at,
                credentials=resolved,
                transport=transport,
                sleeper=sleeper,
            )
        else:
            naver = deferred_result(reference, "naver", at, "hourly NAVER verification limit")
        if naver.status == "failed" and str(naver.error_code or "").casefold() in {
            "024", "unauthorized", "authentication_failed",
        }:
            naver_auth_blocked = True
        persist_verification_result(naver, path)
        output.append(naver)

        used = youtube_search_attempts_on_kst_date(path, at)
        remaining = max(0, youtube_daily_search_budget - used)
        if index >= youtube_term_limit:
            youtube = deferred_result(reference, "youtube", at, "hourly YouTube verification limit")
        elif remaining <= 0:
            youtube = deferred_result(reference, "youtube", at, "daily YouTube search budget reserved")
        else:
            youtube = collect_youtube_context(
                reference,
                at=at,
                credentials=resolved,
                transport=transport,
                max_search_attempts=min(2, remaining),
                sleeper=sleeper,
            )
        persist_verification_result(youtube, path)
        output.append(youtube)

        instagram = _unavailable(
            reference,
            "instagram",
            at,
            "authorized Meta/Instagram data access is not configured",
        )
        if resolved.instagram_access_token:
            instagram = deferred_result(
                reference,
                "instagram",
                at,
                "authorized collector is not enabled in this MVP",
            )
        persist_verification_result(instagram, path)
        output.append(instagram)
    return output


def persist_news_discovery(records: list[dict], path: Path) -> list[dict]:
    """Store article-discovered terms without inserting them into core ranking."""

    initialize_verification_ledger(path)
    stored: list[dict] = []
    with sqlite3.connect(path) as connection:
        for raw in records:
            row = validate_news_evidence(raw)
            normalized = re.sub(r"\s+", "", row["observed_term"].casefold())
            candidate_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
            connection.execute(
                """INSERT INTO news_discovery_candidates
                   (candidate_key,observed_term,first_seen_at,last_seen_at,article_count,
                    core_source_gate,ranking_insertion_performed)
                   VALUES (?,?,?,?,0,'awaiting_x_or_google',0)
                   ON CONFLICT(candidate_key) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                (
                    candidate_key,
                    row["observed_term"],
                    row["retrieved_at"],
                    row["retrieved_at"],
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO news_discovery_evidence
                   (candidate_key,title,publisher,url,published_at,retrieved_at,claims_json,
                    review_status,provenance_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    candidate_key,
                    row["title"],
                    row["publisher"],
                    row["url"],
                    row["published_at"],
                    row["retrieved_at"],
                    json.dumps(row["claims"], ensure_ascii=False, sort_keys=True),
                    row["review_status"],
                    json.dumps(
                        {
                            "schema_version": row["schema_version"],
                            "ranking_evidence": False,
                            "ranking_effect": RANKING_EFFECT,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            count = connection.execute(
                "SELECT COUNT(*) FROM news_discovery_evidence WHERE candidate_key=?",
                (candidate_key,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE news_discovery_candidates SET article_count=? WHERE candidate_key=?",
                (count, candidate_key),
            )
            stored.append(
                {
                    "candidate_key": candidate_key,
                    "observed_term": row["observed_term"],
                    "core_source_gate": "awaiting_x_or_google",
                    "ranking_insertion_performed": False,
                }
            )
    return stored


def mark_news_candidate_core_observed(
    *,
    path: Path,
    observed_term: str,
    source: str,
    observed_at: datetime,
) -> None:
    if source not in {"x", "google_trends"}:
        raise ValueError("only X or Google Trending Now can satisfy the core source gate")
    initialize_verification_ledger(path)
    normalized = re.sub(r"\s+", "", _term(observed_term).casefold())
    candidate_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM news_discovery_candidates WHERE candidate_key=?", (candidate_key,)
        ).fetchone()
        if not exists:
            return
        connection.execute(
            """INSERT OR IGNORE INTO news_core_observation_links
               (candidate_key,source,observed_at) VALUES (?,?,?)""",
            (candidate_key, source, _iso(observed_at)),
        )
        connection.execute(
            """UPDATE news_discovery_candidates
               SET core_source_gate='satisfied_by_x_or_google',
                   ranking_insertion_performed=0
               WHERE candidate_key=?""",
            (candidate_key,),
        )


def read_verification_ledger(path: Path) -> list[dict]:
    initialize_verification_ledger(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT id,observed_at,trend_key,representative_term,provider,status,matched,
                      endpoint,attempt_count,error_code,error_detail,metrics_json,
                      provenance_json,ranking_effect
               FROM provider_verification_runs ORDER BY id"""
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["matched"] = None if item["matched"] is None else bool(item["matched"])
        item["metrics"] = json.loads(item.pop("metrics_json"))
        item["provenance"] = json.loads(item.pop("provenance_json"))
        result.append(item)
    return result


def latest_verification_by_trend(path: Path) -> dict[str, dict]:
    """Return a frontend-safe status block; it deliberately contains no score field."""

    initialize_verification_ledger(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """WITH latest AS (
                 SELECT trend_key,provider,MAX(id) AS run_id
                 FROM provider_verification_runs GROUP BY trend_key,provider
               )
               SELECT runs.id,runs.trend_key,runs.representative_term,runs.provider,
                      runs.observed_at,runs.status,runs.matched,runs.error_code,
                      runs.metrics_json,runs.ranking_effect
               FROM latest JOIN provider_verification_runs AS runs ON runs.id=latest.run_id
               ORDER BY runs.trend_key,runs.provider"""
        ).fetchall()
        evidence_rows = connection.execute(
            """SELECT run_id,item_order,item_type,provider_item_id,title,url,published_at,
                      publisher,metrics_json,provenance_json
               FROM provider_evidence_items ORDER BY run_id,item_order"""
        ).fetchall()
    evidence_by_run: dict[int, list[dict]] = {}
    for row in evidence_rows:
        item = dict(row)
        item["metrics"] = json.loads(item.pop("metrics_json"))
        item["provenance"] = json.loads(item.pop("provenance_json"))
        evidence_by_run.setdefault(int(item.pop("run_id")), []).append(item)
    output: dict[str, dict] = {}
    for row in rows:
        trend = output.setdefault(
            str(row["trend_key"]),
            {
                "representative_term": row["representative_term"],
                "role": "context_and_verification_only",
                "ranking_effect": RANKING_EFFECT,
                "providers": {},
            },
        )
        trend["providers"][str(row["provider"])] = {
            "observed_at": row["observed_at"],
            "status": row["status"],
            "matched": None if row["matched"] is None else bool(row["matched"]),
            "error_code": row["error_code"],
            "metrics": json.loads(row["metrics_json"]),
            "evidence": evidence_by_run.get(int(row["id"]), []),
        }
    return output


def read_news_discovery_queue(path: Path) -> list[dict]:
    initialize_verification_ledger(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT candidate_key,observed_term,first_seen_at,last_seen_at,article_count,
                      core_source_gate,ranking_insertion_performed
               FROM news_discovery_candidates ORDER BY first_seen_at,candidate_key"""
        ).fetchall()
        evidence_rows = connection.execute(
            """SELECT candidate_key,title,publisher,url,published_at,retrieved_at,
                      claims_json,review_status
               FROM news_discovery_evidence
               ORDER BY candidate_key,published_at,url"""
        ).fetchall()
    evidence_by_candidate: dict[str, list[dict]] = {}
    for row in evidence_rows:
        item = dict(row)
        item["claims"] = json.loads(item.pop("claims_json"))
        evidence_by_candidate.setdefault(str(item.pop("candidate_key")), []).append(item)
    result = []
    for row in rows:
        item = dict(row)
        evidence = evidence_by_candidate.get(str(item["candidate_key"]), [])
        item.update({
            "ranking_insertion_performed": bool(item["ranking_insertion_performed"]),
            "ranking_eligible_from_news_alone": False,
            "claim_types": sorted({
                str(claim.get("type"))
                for article in evidence
                for claim in article.get("claims", [])
                if claim.get("type")
            }),
            "evidence": evidence,
        })
        result.append(item)
    return result
