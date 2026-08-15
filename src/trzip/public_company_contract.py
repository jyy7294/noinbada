"""Fail-closed company facts required by the public v4 presentation feed.

These checks are intentionally rank-neutral.  They decide whether an enriched
company can be displayed; they never alter the canonical X/Google score.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse


PUBLIC_MARKET_SESSION_COUNT = 30
LISTING_FRESHNESS_DAYS = 4
LISTING_POST_OBSERVATION_AUDIT_DAYS = 1
MARKET_FIELD_POST_OBSERVATION_AUDIT_DAYS = 1
MARKET_FIELD_FRESHNESS_DAYS = {
    "price_series": 7,
    "market_cap_krw": 7,
    "per": 14,
    "pbr": 14,
    # ROE is a filing-period fact.  A current TTM or latest annual numerator
    # can legitimately predate daily market fields, but not indefinitely.
    "roe_pct": 400,
}
PER_UNAVAILABLE_STATUSES = frozenset({
    "unavailable_loss_making",
    "unavailable_not_reported",
    "unavailable_stale",
})
LISTING_STATUS = "verified_current"
LISTING_EVIDENCE_TYPES = frozenset({
    "exchange_current_security_universe",
    "official_current_security_register",
})
IMAGE_LOGO_VERIFICATIONS = frozenset({
    "verified_safe_svg",
    "verified_raster_min_64px",
})
KEYWORD_COMPANY_LINK_POLICY = "public-keyword-company-link-coverage-v1"


def public_url_is_valid(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return bool(parsed.scheme in {"http", "https"} and parsed.hostname)


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def keyword_company_link_coverage(
    *,
    keywords: object,
    companies: object,
    links: object,
    require_link_metadata: bool = False,
) -> dict:
    """Validate the complete public keyword-to-company bridge.

    A publishable card is not complete merely because two keywords happen to
    have links.  Every displayed keyword and every displayed company must be
    represented by at least one evidence-backed pair, and each company's
    ``matched_keywords`` must describe exactly those pairs.  This contract is
    display-only and has no rank or score authority.
    """

    keyword_rows = list(keywords) if isinstance(keywords, list) else []
    company_rows = list(companies) if isinstance(companies, list) else []
    link_rows = list(links) if isinstance(links, list) else []

    keyword_by_key: dict[str, str] = {}
    duplicate_keywords: set[str] = set()
    for row in keyword_rows:
        value = row.get("text") if isinstance(row, dict) else row
        text = " ".join(str(value or "").split())
        key = _normalized_text(text)
        if not key:
            continue
        if key in keyword_by_key:
            duplicate_keywords.add(text)
        else:
            keyword_by_key[key] = text

    company_by_name: dict[str, dict] = {}
    duplicate_companies: set[str] = set()
    for row in company_rows:
        if not isinstance(row, dict):
            continue
        name = " ".join(str(row.get("company") or "").split())
        if not name:
            continue
        if name in company_by_name:
            duplicate_companies.add(name)
        else:
            company_by_name[name] = row

    linked_keyword_keys: set[str] = set()
    linked_companies: set[str] = set()
    link_keywords_by_company: dict[str, set[str]] = {
        name: set() for name in company_by_name
    }
    link_pairs: set[tuple[str, str]] = set()
    invalid_link_indexes: list[int] = []
    duplicate_pairs: list[str] = []
    for index, row in enumerate(link_rows):
        if not isinstance(row, dict):
            invalid_link_indexes.append(index)
            continue
        keyword_key = _normalized_text(row.get("keyword"))
        company_name = " ".join(str(row.get("company") or "").split())
        company = company_by_name.get(company_name)
        evidence_urls = list(row.get("evidence_urls") or [])
        pair = (keyword_key, company_name)
        if pair in link_pairs:
            duplicate_pairs.append(f"{keyword_key}\u0000{company_name}")
            invalid_link_indexes.append(index)
            continue
        metadata_valid = True
        if require_link_metadata and company is not None:
            metadata_valid = bool(
                str(row.get("stock_code") or "").strip()
                == str(company.get("stock_code") or company.get("ticker") or "").strip()
                and str(row.get("company_role_category") or "").strip()
                == str(company.get("company_role_category") or "").strip()
                and str(row.get("company_role_label") or "").strip()
                == str(company.get("company_role_label") or "").strip()
            )
        if not (
            keyword_key in keyword_by_key
            and company is not None
            and str(
                row.get("connection_explanation")
                or row.get("relationship_reason")
                or ""
            ).strip()
            and evidence_urls
            and all(public_url_is_valid(url) for url in evidence_urls)
            and metadata_valid
        ):
            invalid_link_indexes.append(index)
            continue
        link_pairs.add(pair)
        linked_keyword_keys.add(keyword_key)
        linked_companies.add(company_name)
        link_keywords_by_company[company_name].add(keyword_key)

    matched_keyword_mismatches: list[str] = []
    for company_name, company in company_by_name.items():
        matched_values = list(company.get("matched_keywords") or [])
        matched_keys = [_normalized_text(value) for value in matched_values]
        matched_set = {key for key in matched_keys if key}
        if (
            not matched_set
            or len(matched_set) != len(matched_keys)
            or not matched_set <= set(keyword_by_key)
            or matched_set != link_keywords_by_company[company_name]
        ):
            matched_keyword_mismatches.append(company_name)

    unlinked_keywords = [
        text for key, text in keyword_by_key.items()
        if key not in linked_keyword_keys
    ]
    unlinked_companies = [
        name for name in company_by_name if name not in linked_companies
    ]
    ready = bool(
        keyword_rows
        and company_rows
        and len(keyword_by_key) == len(keyword_rows)
        and len(company_by_name) == len(company_rows)
        and not duplicate_keywords
        and not duplicate_companies
        and not invalid_link_indexes
        and not duplicate_pairs
        and not unlinked_keywords
        and not unlinked_companies
        and not matched_keyword_mismatches
    )
    return {
        "policy_version": KEYWORD_COMPANY_LINK_POLICY,
        "status": "ready" if ready else "incomplete",
        "ready": ready,
        "keyword_count": len(keyword_by_key),
        "company_count": len(company_by_name),
        "valid_link_count": len(link_pairs),
        "linked_keyword_count": len(linked_keyword_keys),
        "linked_company_count": len(linked_companies),
        "unlinked_keywords": unlinked_keywords,
        "unlinked_companies": unlinked_companies,
        "matched_keyword_mismatches": matched_keyword_mismatches,
        "invalid_link_indexes": invalid_link_indexes,
        "duplicate_pairs": duplicate_pairs,
        "ranking_effect": "none",
    }


def finite_number(value: object, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return value > 0 if positive else True


def _date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def market_field_date_is_fresh(
    value: object,
    field: str,
    *,
    observed_at: datetime | None,
) -> bool:
    """Validate a field date against its own economic update cadence."""

    as_of = _date(value)
    max_age_days = MARKET_FIELD_FRESHNESS_DAYS.get(field)
    if as_of is None or max_age_days is None:
        return False
    if observed_at is None:
        return True
    age = observed_at.astimezone(UTC).date() - as_of
    return bool(
        -MARKET_FIELD_POST_OBSERVATION_AUDIT_DAYS
        <= age.days
        <= max_age_days
    )


def _per_contract_is_valid(
    value: dict,
    *,
    source_url: object,
    observed_at: datetime | None,
) -> bool:
    status = str(value.get("per_status") or "").strip()
    per = value.get("per")
    if status == "observed":
        return bool(
            finite_number(per, positive=True)
            and public_url_is_valid(source_url)
            and market_field_date_is_fresh(
                value.get("per_as_of"), "per", observed_at=observed_at
            )
        )
    return bool(status in PER_UNAVAILABLE_STATUSES and per is None)


def listing_verification_is_valid(
    verification: object,
    *,
    exchange: object = None,
    stock_code: object = None,
    observed_at: datetime | None = None,
) -> bool:
    """Accept only a fresh current-universe proof from an exchange/official source."""

    if not isinstance(verification, dict):
        return False
    expected_exchange = str(exchange or "").strip().upper()
    expected_code = str(stock_code or "").strip().upper()
    actual_exchange = str(verification.get("exchange") or "").strip().upper()
    actual_code = str(verification.get("stock_code") or "").strip().upper()
    as_of = _date(verification.get("as_of"))
    if (
        verification.get("status") != LISTING_STATUS
        or verification.get("current_listed") is not True
        or verification.get("evidence_type") not in LISTING_EVIDENCE_TYPES
        or not str(verification.get("evidence_owner") or "").strip()
        or not public_url_is_valid(verification.get("evidence_url"))
        or not as_of
        or verification.get("synthetic") is not False
        or verification.get("estimated") is not False
        or verification.get("ranking_effect") != "none"
        or (expected_exchange and actual_exchange != expected_exchange)
        or (expected_code and actual_code != expected_code)
    ):
        return False
    if observed_at is not None:
        reference_day = observed_at.astimezone(UTC).date()
        age = reference_day - as_of
        if (
            age < timedelta(days=-LISTING_POST_OBSERVATION_AUDIT_DAYS)
            or age > timedelta(days=LISTING_FRESHNESS_DAYS)
        ):
            return False
    return True


def _observed_sessions(value: object) -> bool:
    if not isinstance(value, list) or len(value) != PUBLIC_MARKET_SESSION_COUNT:
        return False
    dates = [str(row.get("date") or "").strip() for row in value if isinstance(row, dict)]
    return bool(
        len(dates) == PUBLIC_MARKET_SESSION_COUNT
        and all(dates)
        and dates == sorted(dates)
        and len(set(dates)) == PUBLIC_MARKET_SESSION_COUNT
        and all(
            isinstance(row, dict) and finite_number(row.get("close"), positive=True)
            for row in value
        )
    )


def market_reference_is_public_ready(
    company: object,
    *,
    observed_at: datetime | None = None,
) -> bool:
    """Validate the pre-projection provider record without inventing UI values."""

    if not isinstance(company, dict):
        return False
    market = company.get("market_reference")
    if not isinstance(market, dict):
        return False
    exchange = company.get("market") or company.get("exchange")
    stock_code = company.get("stock_code") or company.get("ticker")
    summary = market.get("summary") if isinstance(market.get("summary"), dict) else {}
    valuation = market.get("valuation") if isinstance(market.get("valuation"), dict) else {}
    fx = market.get("fx_reference") if isinstance(market.get("fx_reference"), dict) else {}
    source_urls = market.get("source_urls") if isinstance(market.get("source_urls"), dict) else {}
    field_sources = market.get("field_sources") if isinstance(market.get("field_sources"), dict) else {}
    base_source = market.get("source_url")
    fundamentals_source = source_urls.get("fundamentals") or base_source
    latest_price_date = (
        (market.get("daily_ohlcv") or [{}])[-1].get("date")
        if isinstance(market.get("daily_ohlcv"), list)
        and market.get("daily_ohlcv")
        else None
    )
    return bool(
        market.get("status") == "observed"
        and market.get("synthetic") is False
        and market.get("estimated") is False
        and market.get("ranking_effect") == "none"
        and str(market.get("provider") or "").strip()
        and public_url_is_valid(base_source)
        and _observed_sessions(market.get("daily_ohlcv"))
        and str(summary.get("as_of") or "").strip()
        and market_field_date_is_fresh(
            latest_price_date, "price_series", observed_at=observed_at
        )
        and finite_number(summary.get("market_cap_krw"), positive=True)
        and finite_number(summary.get("market_cap"), positive=True)
        and len(str(summary.get("currency") or "").strip().upper()) == 3
        and fx.get("status") == "observed"
        and finite_number(fx.get("rate"), positive=True)
        and str(fx.get("as_of") or "").strip()
        and str(fx.get("provider") or "").strip()
        and public_url_is_valid(fx.get("source_url"))
        and finite_number(valuation.get("pbr"), positive=True)
        and finite_number(valuation.get("roe_pct"))
        and market_field_date_is_fresh(
            valuation.get("market_cap_as_of") or summary.get("as_of"),
            "market_cap_krw",
            observed_at=observed_at,
        )
        and _per_contract_is_valid(
            valuation,
            source_url=field_sources.get("per") or fundamentals_source,
            observed_at=observed_at,
        )
        and market_field_date_is_fresh(
            valuation.get("pbr_as_of"), "pbr", observed_at=observed_at
        )
        and market_field_date_is_fresh(
            (valuation.get("roe_numerator") or {}).get("as_of"),
            "roe_pct",
            observed_at=observed_at,
        )
        and public_url_is_valid(field_sources.get("pbr") or fundamentals_source)
        and public_url_is_valid(field_sources.get("roe_pct") or fundamentals_source)
        and listing_verification_is_valid(
            company.get("listing_verification") or market.get("listing_verification"),
            exchange=exchange,
            stock_code=stock_code,
            observed_at=observed_at,
        )
    )


def market_snapshot_is_public_ready(
    company: object,
    *,
    observed_at: datetime | None = None,
) -> bool:
    """Validate the fully projected v4 market snapshot and field provenance."""

    if not isinstance(company, dict):
        return False
    snapshot = company.get("market_snapshot")
    if not isinstance(snapshot, dict):
        return False
    points = snapshot.get("price_points")
    series = snapshot.get("price_series")
    if not _observed_sessions(points) or not isinstance(series, list):
        return False
    closes = [row["close"] for row in points]
    if len(series) != PUBLIC_MARKET_SESSION_COUNT or series != closes:
        return False
    provenance = snapshot.get("field_provenance")
    if not isinstance(provenance, dict):
        return False
    for field in ("price_series", "market_cap_krw", "pbr", "roe_pct"):
        row = provenance.get(field)
        if (
            not isinstance(row, dict)
            or not str(row.get("provider") or "").strip()
            or not str(row.get("as_of") or "").strip()
            or not public_url_is_valid(row.get("source_url"))
            or row.get("synthetic") is not False
            or row.get("estimated") is not False
            or not market_field_date_is_fresh(
                row.get("as_of"), field, observed_at=observed_at
            )
        ):
            return False
    per_status = str(snapshot.get("per_status") or "").strip()
    if per_status == "observed":
        per_provenance = provenance.get("per")
        if (
            not isinstance(per_provenance, dict)
            or not str(per_provenance.get("provider") or "").strip()
            or not public_url_is_valid(per_provenance.get("source_url"))
            or per_provenance.get("synthetic") is not False
            or per_provenance.get("estimated") is not False
            or not market_field_date_is_fresh(
                per_provenance.get("as_of"), "per", observed_at=observed_at
            )
        ):
            return False
    elif per_status not in PER_UNAVAILABLE_STATUSES or snapshot.get("per") is not None:
        return False
    return bool(
        snapshot.get("status") == "observed"
        and snapshot.get("synthetic") is False
        and snapshot.get("estimated") is False
        and snapshot.get("display_only") is True
        and snapshot.get("ranking_effect") == "none"
        and str(snapshot.get("provider") or "").strip()
        and str(snapshot.get("source") or "").strip()
        and str(snapshot.get("as_of") or "").strip()
        and public_url_is_valid(snapshot.get("source_url"))
        and public_url_is_valid(snapshot.get("price_source_url"))
        and finite_number(snapshot.get("market_cap_krw"), positive=True)
        and snapshot.get("market_cap") == snapshot.get("market_cap_krw")
        and snapshot.get("market_cap_currency") == "KRW"
        and finite_number(snapshot.get("native_market_cap"), positive=True)
        and finite_number(snapshot.get("fx_rate_to_krw"), positive=True)
        and str(snapshot.get("fx_as_of") or "").strip()
        and str(snapshot.get("fx_provider") or "").strip()
        and public_url_is_valid(snapshot.get("fx_source_url"))
        and public_url_is_valid(snapshot.get("market_cap_source_url"))
        and (
            per_status != "observed"
            or finite_number(snapshot.get("per"), positive=True)
        )
        and finite_number(snapshot.get("pbr"), positive=True)
        and finite_number(snapshot.get("roe_pct"))
        and (
            per_status != "observed"
            or public_url_is_valid(snapshot.get("per_source_url"))
        )
        and public_url_is_valid(snapshot.get("pbr_source_url"))
        and public_url_is_valid(snapshot.get("roe_source_url"))
        and listing_verification_is_valid(
            company.get("listing_verification"),
            exchange=company.get("market") or company.get("exchange"),
            stock_code=company.get("stock_code") or company.get("ticker"),
            observed_at=observed_at,
        )
    )


def verified_image_logo_is_public_ready(company: object) -> bool:
    """Reject initials and accept only a verified official-page image asset."""

    if not isinstance(company, dict):
        return False
    width = company.get("logo_asset_width")
    height = company.get("logo_asset_height")
    verification = str(company.get("logo_asset_verification") or "").strip()
    provenance = company.get("logo_provenance")
    logo_url = str(company.get("logo_url") or "").strip()
    source_page = str(company.get("logo_source_page_url") or "").strip()
    sha256 = str(company.get("logo_asset_sha256") or "").strip().casefold()
    if (
        company.get("logo_render_mode") != "image"
        or company.get("logo_asset_source") != "official_page_asset"
        or verification not in IMAGE_LOGO_VERIFICATIONS
        or not logo_url.startswith("https://")
        or not public_url_is_valid(logo_url)
        or not public_url_is_valid(source_page)
        or not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or width <= 0
        or height <= 0
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or not isinstance(provenance, dict)
        or provenance.get("asset_url") != logo_url
        or provenance.get("source_page_url") != source_page
        or provenance.get("verification") != verification
        or provenance.get("sha256") != sha256
    ):
        return False
    if verification == "verified_raster_min_64px" and (width < 64 or height < 64):
        return False
    return True
