from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from urllib.parse import urlparse


ALLOWED_CLAIM_TYPES = {
    "search_growth",
    "product_launch",
    "sales_rank",
    "consumer_behavior",
    "cross_platform_spread",
    "official_relationship",
    "industry_context",
}


class NewsEvidenceError(ValueError):
    pass


def _aware_iso(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NewsEvidenceError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NewsEvidenceError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise NewsEvidenceError(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _safe_https_url(value: object, allowed_hosts: set[str] | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NewsEvidenceError("url is required")
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise NewsEvidenceError("url must be an unauthenticated HTTPS URL")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise NewsEvidenceError("local hosts are not allowed")
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    if host_ip is not None and (
        host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_reserved
        or host_ip.is_unspecified
    ):
        raise NewsEvidenceError("private IP hosts are not allowed")
    if allowed_hosts is not None and host not in {item.casefold() for item in allowed_hosts}:
        raise NewsEvidenceError("publisher host is not allowlisted")
    return value.strip()


def validate_news_evidence(
    record: dict,
    *,
    allowed_hosts: set[str] | None = None,
) -> dict:
    """Validate article evidence used for context or ontology enrichment.

    The returned record is never ranking evidence. An article-discovered term
    must still be observed by X or Google Trending Now before ranking.
    """

    if not isinstance(record, dict):
        raise NewsEvidenceError("record must be an object")
    title = " ".join(str(record.get("title") or "").strip().split())
    publisher = " ".join(str(record.get("publisher") or "").strip().split())
    term = " ".join(str(record.get("observed_term") or "").strip().split())
    if not title or not publisher or not term:
        raise NewsEvidenceError("title, publisher, and observed_term are required")
    url = _safe_https_url(record.get("url"), allowed_hosts)
    published_at = _aware_iso(record.get("published_at"), "published_at")
    retrieved_at = _aware_iso(record.get("retrieved_at"), "retrieved_at")
    raw_claims = record.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise NewsEvidenceError("at least one claim is required")
    claims = []
    for raw in raw_claims:
        if not isinstance(raw, dict):
            raise NewsEvidenceError("each claim must be an object")
        claim_type = str(raw.get("type") or "").strip()
        text = " ".join(str(raw.get("text") or "").strip().split())
        if claim_type not in ALLOWED_CLAIM_TYPES or not text:
            raise NewsEvidenceError("claim type or text is invalid")
        claims.append({"type": claim_type, "text": text})

    review_status = str(record.get("review_status") or "unreviewed").strip()
    if review_status not in {"unreviewed", "reviewed", "approved", "rejected"}:
        raise NewsEvidenceError("review_status is invalid")
    evidence_publishable = review_status == "approved"
    return {
        "schema_version": "trzip-news-evidence-v1",
        "title": title,
        "publisher": publisher,
        "url": url,
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "observed_term": term,
        "claims": claims,
        "claim_types": sorted({claim["type"] for claim in claims}),
        "review_status": review_status,
        "evidence_publishable": evidence_publishable,
        "ranking_evidence": False,
    }


def build_discovery_queue(records: list[dict]) -> list[dict]:
    """Build a review queue; news-only terms never enter unified ranking."""

    queue: dict[str, dict] = {}
    for record in records:
        validated = validate_news_evidence(record)
        key = validated["observed_term"].casefold()
        item = queue.setdefault(
            key,
            {
                "term": validated["observed_term"],
                "article_urls": [],
                "claim_types": set(),
                "ranking_eligible": False,
                "required_source_observation": ["x", "google_trends"],
                "status": "awaiting_x_or_google_observation",
            },
        )
        item["article_urls"].append(validated["url"])
        item["claim_types"].update(validated["claim_types"])
    return [
        {**item, "article_urls": sorted(set(item["article_urls"])), "claim_types": sorted(item["claim_types"])}
        for _, item in sorted(queue.items())
    ]
