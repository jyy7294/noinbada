from __future__ import annotations

import io
import html
import json
import math
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import Lock

from .hourly_store import load_local_env


OHLCV_COLUMNS = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
    "거래대금": "trading_value",
    "등락률": "change_pct",
}

FUNDAMENTAL_COLUMNS = {
    "BPS": "bps",
    "PER": "per",
    "PBR": "pbr",
    "EPS": "eps",
    "DIV": "dividend_yield_pct",
    "DPS": "dps",
}

KRX_DATA_SOURCE_URL = "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"
KRX_KIND_CURRENT_LIST_URL = (
    "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
)

YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_FUNDAMENTALS_ENDPOINT = (
    "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/"
    "timeseries/{symbol}"
)
YAHOO_PUBLIC_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"
YAHOO_MARKET_CACHE_TTL_SECONDS = 15 * 60
YAHOO_MARKET_CACHE_MAX_ENTRIES = 256
YAHOO_MARKET_TIMEOUT_SECONDS = 8
YAHOO_MARKET_MAX_ATTEMPTS = 3
YAHOO_MARKET_RETRY_BACKOFF_SECONDS = 0.1
# Yahoo's trailing P/E series is market-sensitive rather than a filing-period
# fact.  A historical positive point must not be carried forward after the
# issuer becomes loss-making (or simply stops reporting a current ratio).
YAHOO_PER_FRESHNESS_DAYS = 14
YAHOO_FUNDAMENTAL_TYPES = (
    "trailingMarketCap",
    "quarterlyMarketCap",
    "trailingPeRatio",
    "quarterlyStockholdersEquity",
    "annualStockholdersEquity",
    "quarterlyTotalStockholderEquity",
    "annualTotalStockholderEquity",
    "trailingNetIncome",
    "annualNetIncome",
)

_YAHOO_MARKET_CACHE: dict[str, tuple[float, dict]] = {}
_YAHOO_MARKET_CACHE_LOCK = Lock()


def _parse_krx_kind_current_register(document: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for raw_row in re.findall(
        r"<tr[^>]*>(.*?)</tr>", document, flags=re.IGNORECASE | re.DOTALL
    ):
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(
                r"<[^>]+>", " ", raw_cell, flags=re.IGNORECASE | re.DOTALL
            ))).strip()
            for raw_cell in re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>",
                raw_row,
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]
        if len(cells) < 3 or not re.fullmatch(r"\d{6}", cells[2]):
            continue
        market = {
            "유가": "KOSPI",
            "유가증권": "KOSPI",
            "코스피": "KOSPI",
            "코스닥": "KOSDAQ",
            "코넥스": "KONEX",
        }.get(cells[1])
        if market:
            rows.append((cells[2], market))
    unique_rows = tuple(sorted(set(rows)))
    markets_by_code: dict[str, set[str]] = {}
    for code, market in unique_rows:
        markets_by_code.setdefault(code, set()).add(market)
    if (
        len(markets_by_code) < 1_000
        or any(len(markets) != 1 for markets in markets_by_code.values())
    ):
        raise ValueError("KRX KIND current listed-company register is incomplete")
    return unique_rows


@lru_cache(maxsize=2)
def _krx_kind_current_security_universe(
    retrieved_on: str,
) -> tuple[tuple[str, str], ...]:
    """Read KRX KIND's current listed-company register once per UTC day.

    The register is independent of any one ticker's price history.  That is
    essential for detecting a recently delisted code whose final OHLCV row is
    still available.  ``retrieved_on`` is a cache/provenance key; KIND serves
    the current register rather than a historical reconstruction.
    """

    request = urllib.request.Request(
        KRX_KIND_CURRENT_LIST_URL,
        headers={"User-Agent": "TRZIP/0.1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        if content_type != "application/vnd.ms-excel":
            raise ValueError("KRX KIND current register MIME type is invalid")
        document = response.read().decode("euc-kr", errors="strict")
    return _parse_krx_kind_current_register(document)


def krx_current_listing_verification(
    stock_code: str,
    observed_at: datetime,
    *,
    exchange: str = "KRX",
) -> dict:
    """Return fail-closed current-list proof from the official KRX register."""

    code = str(stock_code or "").strip()
    retrieved_on = datetime.now(UTC).date().isoformat()
    expected_exchange = str(exchange or "KRX").strip().upper()
    if expected_exchange not in {"KRX", "KOSPI", "KOSDAQ", "KONEX"}:
        expected_exchange = "KRX"
    verification = {
        "status": "unavailable",
        "current_listed": False,
        "exchange": expected_exchange,
        "stock_code": code,
        "as_of": None,
        "evidence_owner": "KRX KIND",
        "evidence_type": "official_current_security_register",
        "evidence_url": KRX_KIND_CURRENT_LIST_URL,
        "synthetic": False,
        "estimated": False,
        "ranking_effect": "none",
    }
    if len(code) != 6 or not code.isdigit() or observed_at.tzinfo is None:
        return verification
    try:
        current_markets = dict(_krx_kind_current_security_universe(retrieved_on))
    except Exception:
        return verification
    actual_market = current_markets.get(code)
    current = bool(
        actual_market
        and (expected_exchange == "KRX" or actual_market == expected_exchange)
    )
    verification.update({
        "status": "verified_current" if current else "verified_inactive",
        "current_listed": current,
        "as_of": retrieved_on,
    })
    return verification


def _yahoo_fx_symbol_to_krw(currency: str) -> str:
    """Return Yahoo's quoted KRW cross for one ISO-like currency code."""

    clean = str(currency or "").strip().upper()
    if clean == "USD":
        # Yahoo's long-standing USD/KRW symbol is KRW=X.
        return "KRW=X"
    if not re.fullmatch(r"[A-Z]{3}", clean) or clean == "KRW":
        raise ValueError("unsupported_fx_currency")
    return f"{clean}KRW=X"

REPORT_LABELS = {
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
    "11011": "사업보고서",
}

FINANCIAL_ACCOUNT_ALIASES = {
    "revenue": ("매출액", "영업수익"),
    "operating_profit": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)"),
    "assets": ("자산총계",),
    "liabilities": ("부채총계",),
    "equity": ("자본총계",),
}


def integration_status() -> dict:
    load_local_env()
    return {
        "opendart": {"configured": bool(os.environ.get("OPENDART_API_KEY", "").strip()),
                     "role": "issuer identity, company overview and latest available major financial accounts"},
        "pykrx": {"configured": True,
                  "role": "Korean ticker name, daily OHLCV and PER/PBR/EPS/BPS/DIV/DPS reference; never realtime quote or trend ranking"},
        "yahoo_finance": {
            "configured": True,
            "role": "Overseas listed-company daily market and reported-fundamental reference; never trend ranking or relationship evidence",
        },
    }


def _json_request(url: str, *, method: str = "GET", headers: dict | None = None,
                  body: dict | None = None, timeout: int = 20) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"User-Agent": "TRZIP/0.1", **(headers or {})}
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json;charset=UTF-8")
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _json_request_with_retry(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: dict | None = None,
    timeout: int = 20,
    max_attempts: int = YAHOO_MARKET_MAX_ATTEMPTS,
) -> dict:
    """Retry only transient transport failures for unauthenticated market APIs.

    A definitive client response such as Yahoo's 404 for a delisted symbol is
    returned immediately.  This keeps the adapter quick and prevents a missing
    security from being mistaken for a temporary outage.
    """

    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return _json_request(
                url,
                method=method,
                headers=headers,
                body=body,
                timeout=timeout,
            )
        except Exception as exc:
            last_error = exc
            http_status = getattr(exc, "code", None)
            if http_status is not None:
                retryable = http_status == 429 or 500 <= int(http_status) <= 599
            else:
                retryable = isinstance(
                    exc,
                    (TimeoutError, ConnectionError, urllib.error.URLError),
                )
            if not retryable or attempt + 1 >= max_attempts:
                raise
            time.sleep(YAHOO_MARKET_RETRY_BACKOFF_SECONDS * (2 ** attempt))
    # The loop either returns or raises, but retain an explicit fail-closed
    # guard in case max_attempts is changed incorrectly in the future.
    if last_error is not None:
        raise last_error
    raise ValueError("max_attempts_must_be_positive")


def opendart_company(company_name: str, stock_code: str | None = None) -> dict:
    """Resolve a listed issuer and return its OpenDART company overview.

    A six-digit stock code is the primary key when it is available. Exact
    issuer-name matching remains as the fallback for callers that only know a
    company name.
    """
    load_local_env()
    key = os.environ.get("OPENDART_API_KEY", "").strip()
    if not key:
        return {"status": "unavailable", "company": company_name, "reason": "OPENDART_API_KEY not configured"}
    try:
        root = _opendart_corp_root(key)
        def normalize_issuer(value: str) -> str:
            compact = re.sub(r"\s+", "", value).casefold()
            return re.sub(r"(?:\(주\)|㈜|주식회사)$", "", compact)
        requested_stock_code = str(stock_code or "").strip()
        if requested_stock_code and (
            len(requested_stock_code) != 6 or not requested_stock_code.isdigit()
        ):
            return {
                "status": "invalid",
                "company": company_name,
                "reason": "six-digit stock code required",
            }
        target = normalize_issuer(company_name)
        matches = []
        for node in root.findall("list"):
            name = (node.findtext("corp_name") or "").strip()
            listed_code = (node.findtext("stock_code") or "").strip()
            if (
                requested_stock_code and listed_code == requested_stock_code
            ) or (
                not requested_stock_code and normalize_issuer(name) == target
            ):
                matches.append({child.tag: (child.text or "").strip() for child in node})
        if not matches:
            reason = (
                "OpenDART stock code not found"
                if requested_stock_code
                else "exact OpenDART issuer name not found"
            )
            return {"status": "not_found", "company": company_name, "reason": reason}
        match = sorted(matches, key=lambda item: bool(item.get("stock_code")), reverse=True)[0]
        overview_query = urllib.parse.urlencode({"crtfc_key": key, "corp_code": match["corp_code"]})
        overview = _json_request("https://opendart.fss.or.kr/api/company.json?" + overview_query)
        if overview.get("status") != "000":
            return {"status": "error", "company": company_name, "reason": overview.get("message", "OpenDART error")}
        financial_snapshot = opendart_financial_snapshot(
            match["corp_code"],
            company_name=company_name,
            stock_code=match.get("stock_code") or str(stock_code or ""),
        )
        return {"status": "verified", "company": company_name, "corp_code": match["corp_code"],
                "stock_code": match.get("stock_code") or None, "modify_date": match.get("modify_date"),
                "overview": {key: overview.get(key) for key in ("corp_name", "corp_name_eng", "stock_name", "stock_code", "ceo_nm", "corp_cls", "adres", "hm_url", "est_dt")},
                "financial_snapshot": financial_snapshot}
    except Exception as exc:
        return {"status": "error", "company": company_name, "reason": f"{type(exc).__name__}: {exc}"}


def _public_opendart_identity(
    result: dict,
    *,
    company_name: str,
    stock_code: str,
    observed_at: datetime,
) -> dict:
    """Return a credential-free issuer identity record for the frontend.

    OpenDART is issuer metadata only.  It cannot prove the trend relationship
    and never changes score, rank, lane, company eligibility, or relation tier.
    """

    status = str(result.get("status") or "error")
    overview = result.get("overview") if isinstance(result.get("overview"), dict) else {}
    returned_code = str(result.get("stock_code") or overview.get("stock_code") or "").strip()
    if status == "verified" and returned_code != stock_code:
        status = "stock_code_mismatch"
        overview = {}
    homepage = str(overview.get("hm_url") or "").strip()
    if homepage and not homepage.startswith(("http://", "https://")):
        homepage = "https://" + homepage.lstrip("/")
    if homepage and urllib.parse.urlparse(homepage).scheme not in {"http", "https"}:
        homepage = ""
    return {
        "status": status,
        "provider": "opendart",
        "company": company_name,
        "stock_code": stock_code,
        "legal_name": str(overview.get("corp_name") or "").strip() or None,
        "english_name": str(overview.get("corp_name_eng") or "").strip() or None,
        "stock_name": str(overview.get("stock_name") or "").strip() or None,
        "market_class": str(overview.get("corp_cls") or "").strip() or None,
        "homepage": homepage or None,
        "established_date": str(overview.get("est_dt") or "").strip() or None,
        "corp_code": str(result.get("corp_code") or "").strip() or None,
        "financial_snapshot": _public_financial_snapshot(
            result.get("financial_snapshot"),
            company_name=company_name,
            stock_code=stock_code,
            observed_at=observed_at,
        ),
        "retrieved_at": observed_at.astimezone(UTC).isoformat(),
        "ranking_effect": "none",
        "relationship_evidence": False,
    }


def enrich_company_identities(
    companies: list[dict],
    *,
    database_path: Path,
    observed_at: datetime,
    verified_ttl_days: int = 30,
    retry_ttl_hours: int = 24,
) -> tuple[dict[str, dict], dict]:
    """Resolve and persist unique OpenDART identities with bounded retries."""

    if observed_at.tzinfo is None:
        raise ValueError("company identity timestamp must be timezone-aware")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    requested = {
        str(company.get("stock_code") or "").strip(): str(company.get("company") or "").strip()
        for company in companies
        if str(company.get("stock_code") or "").strip()
        and str(company.get("company") or "").strip()
    }
    external_disabled = os.environ.get(
        "TRZIP_DISABLE_EXTERNAL_COMPANY_IDENTITY", ""
    ).strip().casefold() in {"1", "true", "yes"}
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS company_identity_cache (
                   stock_code TEXT PRIMARY KEY,
                   company_name TEXT NOT NULL,
                   status TEXT NOT NULL,
                   payload_json TEXT NOT NULL,
                   observed_at TEXT NOT NULL
               )"""
        )
        rows = {}
        for row in connection.execute(
            "SELECT stock_code,company_name,status,payload_json,observed_at "
            "FROM company_identity_cache"
        ):
            try:
                payload = json.loads(str(row[3]))
                cached_at = datetime.fromisoformat(str(row[4]))
                if not isinstance(payload, dict) or cached_at.tzinfo is None:
                    raise ValueError("invalid cached company identity")
            except (json.JSONDecodeError, TypeError, ValueError):
                # A damaged cache row must never stop the hourly publication.
                # Treat it as a miss and replace it with a fresh lookup below.
                continue
            rows[str(row[0])] = {
                "company_name": str(row[1]),
                "status": str(row[2]),
                "payload": payload,
                "observed_at": cached_at,
            }
        resolved: dict[str, dict] = {}
        fetched = 0
        reused = 0
        for stock_code, company_name in sorted(requested.items()):
            cached = rows.get(stock_code)
            if cached and cached["company_name"] == company_name:
                ttl = (
                    timedelta(days=max(1, verified_ttl_days))
                    if cached["status"] == "verified"
                    else timedelta(hours=max(1, retry_ttl_hours))
                )
                if observed_at.astimezone(UTC) - cached["observed_at"].astimezone(UTC) < ttl:
                    resolved[stock_code] = cached["payload"]
                    reused += 1
                    continue
            upstream = (
                {
                    "status": "unavailable",
                    "company": company_name,
                    "reason": "external_company_identity_disabled",
                }
                if external_disabled
                else opendart_company(company_name, stock_code=stock_code)
            )
            payload = _public_opendart_identity(
                upstream,
                company_name=company_name,
                stock_code=stock_code,
                observed_at=observed_at,
            )
            connection.execute(
                """INSERT INTO company_identity_cache
                   (stock_code,company_name,status,payload_json,observed_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(stock_code) DO UPDATE SET
                     company_name=excluded.company_name,
                     status=excluded.status,
                     payload_json=excluded.payload_json,
                     observed_at=excluded.observed_at""",
                (
                    stock_code,
                    company_name,
                    payload["status"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    observed_at.astimezone(UTC).isoformat(),
                ),
            )
            resolved[stock_code] = payload
            fetched += 1
        connection.commit()
    counts: dict[str, int] = {}
    for payload in resolved.values():
        status = str(payload.get("status") or "error")
        counts[status] = counts.get(status, 0) + 1
    financial_counts: dict[str, int] = {}
    for payload in resolved.values():
        financial_status = str(
            (payload.get("financial_snapshot") or {}).get("status") or "unavailable"
        )
        financial_counts[financial_status] = financial_counts.get(financial_status, 0) + 1
    return resolved, {
        "provider": "opendart",
        "requested": len(requested),
        "fetched": fetched,
        "reused": reused,
        "status_counts": counts,
        "financial_status_counts": financial_counts,
        "verified_ttl_days": max(1, verified_ttl_days),
        "retry_ttl_hours": max(1, retry_ttl_hours),
        "ranking_effect": "none",
        "relationship_evidence": False,
    }


def _report_candidates(as_of: datetime) -> list[tuple[int, str]]:
    """Return bounded newest-to-oldest OpenDART report candidates."""

    year = as_of.year
    candidates: list[tuple[int, str]] = []
    if as_of.month >= 11:
        candidates.append((year, "11014"))
    if as_of.month >= 8:
        candidates.append((year, "11012"))
    if as_of.month >= 5:
        candidates.append((year, "11013"))
    candidates.append((year - 1, "11011"))
    return candidates


def _amount(value: object) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text == "-":
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        parsed = int(text)
    except ValueError:
        return None
    return -parsed if negative else parsed


def _pick_financial_accounts(rows: list[dict]) -> dict[str, dict]:
    preferred = [row for row in rows if row.get("fs_div") == "CFS"] or [
        row for row in rows if row.get("fs_div") == "OFS"
    ]
    accounts: dict[str, dict] = {}
    for key, aliases in FINANCIAL_ACCOUNT_ALIASES.items():
        matches = [
            row for row in preferred
            if str(row.get("account_nm") or "").strip() in aliases
        ]
        if not matches:
            continue
        row = sorted(matches, key=lambda item: int(item.get("ord") or 999999))[0]
        current = _amount(row.get("thstrm_add_amount") or row.get("thstrm_amount"))
        previous = _amount(row.get("frmtrm_add_amount") or row.get("frmtrm_amount"))
        accounts[key] = {
            "label": str(row.get("account_nm") or "").strip(),
            "current": current,
            "previous": previous,
            "currency": str(row.get("currency") or "KRW").strip() or "KRW",
        }
    return accounts


def opendart_financial_snapshot(
    corp_code: str,
    *,
    company_name: str,
    stock_code: str,
    as_of: datetime | None = None,
) -> dict:
    """Fetch the latest available bounded major-account snapshot from OpenDART.

    This is issuer disclosure context only. It is never rank evidence, relation
    evidence, a realtime value, or a forecast.
    """

    load_local_env()
    key = os.environ.get("OPENDART_API_KEY", "").strip()
    observed_at = (as_of or datetime.now(UTC)).astimezone(UTC)
    if not key:
        return {
            "status": "unavailable",
            "provider": "opendart",
            "company": company_name,
            "stock_code": stock_code,
            "reason": "opendart_api_key_not_configured",
        }
    for business_year, report_code in _report_candidates(observed_at):
        query = urllib.parse.urlencode({
            "crtfc_key": key,
            "corp_code": corp_code,
            "bsns_year": str(business_year),
            "reprt_code": report_code,
        })
        try:
            response = _json_request(
                "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?" + query
            )
        except Exception:
            continue
        if response.get("status") != "000" or not isinstance(response.get("list"), list):
            continue
        rows = [row for row in response["list"] if isinstance(row, dict)]
        accounts = _pick_financial_accounts(rows)
        if not accounts:
            continue
        first = rows[0]
        receipt_no = str(first.get("rcept_no") or "").strip()
        fs_div = "CFS" if any(row.get("fs_div") == "CFS" for row in rows) else "OFS"
        return {
            "status": "observed",
            "provider": "opendart",
            "company": company_name,
            "stock_code": stock_code,
            "corp_code": corp_code,
            "business_year": business_year,
            "report_code": report_code,
            "report_label": REPORT_LABELS[report_code],
            "financial_statement_division": fs_div,
            "accounts": accounts,
            "filing_receipt_no": receipt_no or None,
            "filing_url": (
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"
                if receipt_no else None
            ),
            "retrieved_at": observed_at.isoformat(),
            "ranking_effect": "none",
            "relationship_evidence": False,
            "note": "OpenDART 공시 주요계정 참고값이며 정정공시로 변경될 수 있음",
        }
    return {
        "status": "not_found",
        "provider": "opendart",
        "company": company_name,
        "stock_code": stock_code,
        "reason": "latest_major_accounts_not_found",
    }


def _public_financial_snapshot(
    value: object,
    *,
    company_name: str,
    stock_code: str,
    observed_at: datetime,
) -> dict:
    snapshot = value if isinstance(value, dict) else {}
    status = str(snapshot.get("status") or "unavailable")
    if status != "observed":
        safe_status = status if status in {"unavailable", "not_found", "error"} else "unavailable"
        return {
            "status": safe_status,
            "provider": "opendart",
            "company": company_name,
            "stock_code": stock_code,
            "reason": str(snapshot.get("reason") or f"financial_snapshot_{safe_status}"),
            "retrieved_at": observed_at.astimezone(UTC).isoformat(),
            "ranking_effect": "none",
            "relationship_evidence": False,
        }
    accounts = {}
    for name in FINANCIAL_ACCOUNT_ALIASES:
        row = (snapshot.get("accounts") or {}).get(name)
        if isinstance(row, dict):
            accounts[name] = {
                "label": str(row.get("label") or name),
                "current": row.get("current") if isinstance(row.get("current"), int) else None,
                "previous": row.get("previous") if isinstance(row.get("previous"), int) else None,
                "currency": str(row.get("currency") or "KRW"),
            }
    return {
        "status": "observed",
        "provider": "opendart",
        "company": company_name,
        "stock_code": stock_code,
        "corp_code": str(snapshot.get("corp_code") or "") or None,
        "business_year": int(snapshot.get("business_year")),
        "report_code": str(snapshot.get("report_code")),
        "report_label": str(snapshot.get("report_label")),
        "financial_statement_division": str(snapshot.get("financial_statement_division")),
        "accounts": accounts,
        "filing_receipt_no": snapshot.get("filing_receipt_no"),
        "filing_url": snapshot.get("filing_url"),
        "retrieved_at": str(snapshot.get("retrieved_at") or observed_at.astimezone(UTC).isoformat()),
        "ranking_effect": "none",
        "relationship_evidence": False,
        "note": "OpenDART 공시 주요계정 참고값이며 정정공시로 변경될 수 있음",
    }


@lru_cache(maxsize=2)
def _opendart_corp_root(key: str) -> ET.Element:
    """Download the OpenDART issuer index once per E2E process."""
    query = urllib.parse.urlencode({"crtfc_key": key})
    request = urllib.request.Request("https://opendart.fss.or.kr/api/corpCode.xml?" + query,
                                     headers={"User-Agent": "TRZIP/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        archive = response.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        return ET.fromstring(zipped.read("CORPCODE.xml"))


def pykrx_stock(stock_code: str, base_date: str | None = None, lookback_days: int = 45) -> dict:
    """Return a Korean ticker name and recent daily OHLCV through pykrx.

    This adapter intentionally does not describe the last daily row as a realtime
    quote and does not use it to prove a trend-company relationship.
    """
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"status": "invalid", "stock_code": stock_code, "reason": "six-digit stock code required"}
    end = datetime.strptime(base_date, "%Y%m%d") if base_date else datetime.now()
    start = end - timedelta(days=max(14, min(lookback_days, 120)))
    try:
        from contextlib import redirect_stderr, redirect_stdout
        quiet = io.StringIO()
        with redirect_stdout(quiet), redirect_stderr(quiet):
            from pykrx import stock
            name = stock.get_market_ticker_name(code)
            frame = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
            try:
                fundamental_frame = stock.get_market_fundamental_by_date(
                    start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code
                )
            except Exception:
                fundamental_frame = None
            try:
                market_cap_frame = stock.get_market_cap_by_date(
                    start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code
                )
            except Exception:
                market_cap_frame = None
        rows = []
        for at, values in frame.tail(30).iterrows():
            normalized = {
                OHLCV_COLUMNS.get(str(key), str(key)): _scalar(value)
                for key, value in values.items()
            }
            rows.append({"date": at.strftime("%Y-%m-%d"), **normalized})
        if not rows:
            return {
                "status": "not_found",
                "provider": "pykrx",
                "source_url": KRX_DATA_SOURCE_URL,
                "stock_code": code,
                "name": name or None,
                "reason": "pykrx returned no daily OHLCV for requested range",
                "daily_ohlcv": [],
                "summary": {
                    "as_of": None,
                    "close": None,
                    "close_krw": None,
                    "daily_change_pct": None,
                    "volume": None,
                    "currency": "KRW",
                    "market_cap": None,
                    "market_cap_krw": None,
                },
                "valuation": {},
                "data_mode": "unavailable",
                "synthetic": False,
                "estimated": False,
                "ranking_effect": "none",
                "relationship_evidence": False,
            }
        reaction = _market_reaction(rows)
        latest = rows[-1] if rows else None
        listing_verification = krx_current_listing_verification(
            code, end.replace(tzinfo=UTC)
        )
        if listing_verification["status"] == "verified_inactive":
            return {
                "status": "not_found",
                "provider": "pykrx",
                "source_url": KRX_DATA_SOURCE_URL,
                "stock_code": code,
                "name": name or None,
                "reason": "not_in_current_krx_security_universe",
                "listing_verification": listing_verification,
                "daily_ohlcv": [],
                "synthetic": False,
                "estimated": False,
                "ranking_effect": "none",
                "relationship_evidence": False,
            }
        previous = rows[-2] if len(rows) > 1 else None
        close = float(latest.get("close") or 0) if latest else 0
        previous_close = float(previous.get("close") or 0) if previous else 0
        daily_change_pct = (
            round((close / previous_close - 1) * 100, 2)
            if close and previous_close else None
        )
        valuation = {}
        if fundamental_frame is not None and not fundamental_frame.empty:
            latest_fundamental = fundamental_frame.iloc[-1]
            valuation = {
                FUNDAMENTAL_COLUMNS.get(str(key), str(key)): _scalar(value)
                for key, value in latest_fundamental.items()
            }
            fundamental_as_of = fundamental_frame.index[-1].strftime("%Y-%m-%d")
            if _safe_yahoo_number(valuation.get("per")) is not None and valuation["per"] > 0:
                valuation.update({
                    "per_status": "observed",
                    "per_as_of": fundamental_as_of,
                    "per_type": "krxDailyPer",
                    "per_period_type": "DAILY",
                })
            else:
                valuation.update({
                    "per": None,
                    "per_status": "unavailable_not_reported",
                })
            if _safe_yahoo_number(valuation.get("pbr")) is not None and valuation["pbr"] > 0:
                valuation.update({
                    "pbr_as_of": fundamental_as_of,
                    "pbr_type": "krxDailyPbr",
                    "pbr_period_type": "DAILY",
                })
            else:
                valuation["pbr"] = None
        market_cap = None
        if market_cap_frame is not None and not market_cap_frame.empty:
            latest_market_cap = market_cap_frame.iloc[-1]
            raw_market_cap = latest_market_cap.get("시가총액")
            if raw_market_cap is not None:
                market_cap = int(_scalar(raw_market_cap))
                valuation["market_cap_as_of"] = market_cap_frame.index[-1].strftime(
                    "%Y-%m-%d"
                )
                valuation["market_cap_type"] = "krxDailyMarketCap"
                valuation["market_cap_period_type"] = "DAILY"
        return {"status": "observed", "provider": "pykrx", "source_url": KRX_DATA_SOURCE_URL,
                "stock_code": code,
                "name": name or None, "daily_ohlcv": rows,
                "listing_verification": listing_verification,
                "latest_daily": latest,
                "summary": {
                    "as_of": latest.get("date") if latest else None,
                    "close": int(close) if close else None,
                    "close_krw": int(close) if close else None,
                    "daily_change_pct": daily_change_pct,
                    "volume": int(latest.get("volume") or 0) if latest else None,
                    "currency": "KRW",
                    "market_cap": market_cap,
                    "market_cap_krw": market_cap,
                 },
                "fx_reference": {
                    "status": "observed",
                    "provider": "identity",
                    "from_currency": "KRW",
                    "to_currency": "KRW",
                    "rate": 1.0,
                    "as_of": latest.get("date") if latest else None,
                    "source_url": KRX_DATA_SOURCE_URL,
                    "synthetic": False,
                    "estimated": False,
                    "ranking_effect": "none",
                },
                "valuation": valuation,
                "market_reaction": reaction,
                "synthetic": False,
                "estimated": False,
                "ranking_effect": "none",
                "relationship_evidence": False,
                "note": "daily reference data; not realtime, not a forecast, and not relation evidence"}
    except Exception as exc:
        return {"status": "error", "stock_code": code, "reason": f"{type(exc).__name__}: {exc}"}


def yahoo_finance_symbol(ticker: str, exchange: str) -> str:
    """Return the Yahoo symbol for a supported overseas exchange.

    The transformation is intentionally narrow so arbitrary URL fragments can
    never enter the unauthenticated Yahoo endpoints.
    """

    clean_exchange = str(exchange or "").strip().upper()
    clean_ticker = str(ticker or "").strip().upper()
    if clean_exchange not in {
        "NASDAQ", "NYSE", "TSE", "HKEX", "KRX", "KOSPI", "KOSDAQ"
    }:
        raise ValueError("unsupported_exchange")
    if clean_exchange in {"KRX", "KOSPI", "KOSDAQ"}:
        if not re.fullmatch(r"\d{6}", clean_ticker):
            raise ValueError("invalid_krx_ticker")
        # KRX is a generic upstream label.  Try the main-board suffix first;
        # callers that know KOSDAQ pass it explicitly and receive .KQ.
        return clean_ticker + (".KQ" if clean_exchange == "KOSDAQ" else ".KS")
    if clean_exchange == "HKEX":
        if not re.fullmatch(r"\d{1,4}", clean_ticker):
            raise ValueError("invalid_hkex_ticker")
        return clean_ticker.zfill(4) + ".HK"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", clean_ticker):
        raise ValueError("invalid_ticker")
    if clean_ticker.endswith((".T", ".HK")):
        raise ValueError("ticker_must_not_include_exchange_suffix")
    return clean_ticker + ".T" if clean_exchange == "TSE" else clean_ticker


def clear_yahoo_market_cache() -> None:
    """Clear the bounded in-process Yahoo cache (primarily for deterministic tests)."""

    with _YAHOO_MARKET_CACHE_LOCK:
        _YAHOO_MARKET_CACHE.clear()


def _yahoo_unavailable(
    ticker: str,
    exchange: str,
    reason: str,
    *,
    symbol: str | None = None,
    error_type: str | None = None,
    http_status: int | None = None,
) -> dict:
    result = {
        "status": "unavailable",
        "provider": "yahoo_finance",
        "ticker": str(ticker or "").strip(),
        "exchange": str(exchange or "").strip().upper(),
        "yahoo_symbol": symbol,
        "reason": reason,
        "source_url": (
            YAHOO_PUBLIC_QUOTE_URL.format(
                symbol=urllib.parse.quote(symbol, safe=".-")
            )
            if symbol else None
        ),
        "daily_ohlcv": [],
        "summary": {
            "as_of": None,
            "currency": None,
            "close": None,
            "daily_change": None,
            "daily_change_pct": None,
            "market_cap": None,
            "close_krw": None,
            "market_cap_krw": None,
        },
        "fx_reference": {
            "status": "unavailable",
            "provider": "yahoo_finance",
            "from_currency": None,
            "to_currency": "KRW",
            "rate": None,
            "as_of": None,
            "source_url": None,
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        },
        "valuation": {
            "status": "unavailable",
            "per": None,
            "pbr": None,
            "roe_pct": None,
            "equity": None,
            "net_income": None,
        },
        "data_mode": "unavailable",
        "synthetic": False,
        "estimated": False,
        "ranking_effect": "none",
        "relationship_evidence": False,
    }
    if error_type:
        result["error_type"] = error_type
    if http_status is not None:
        result["http_status"] = int(http_status)
    return result


def _safe_yahoo_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_yahoo_chart(payload: object) -> tuple[list[dict], dict]:
    if not isinstance(payload, dict):
        raise ValueError("chart_payload_invalid")
    chart = payload.get("chart")
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError("chart_result_missing")
    result = results[0]
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote = quotes[0] if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict) else None
    if not isinstance(timestamps, list) or not isinstance(quote, dict):
        raise ValueError("chart_series_missing")

    rows: list[dict] = []
    for index, raw_timestamp in enumerate(timestamps):
        timestamp = _safe_yahoo_number(raw_timestamp)
        closes = quote.get("close")
        close = (
            _safe_yahoo_number(closes[index])
            if isinstance(closes, list) and index < len(closes)
            else None
        )
        if timestamp is None or close is None:
            continue
        row = {
            "date": datetime.fromtimestamp(int(timestamp), UTC).date().isoformat(),
            "open": None,
            "high": None,
            "low": None,
            "close": close,
            "volume": None,
        }
        for name in ("open", "high", "low", "volume"):
            values = quote.get(name)
            if isinstance(values, list) and index < len(values):
                row[name] = _safe_yahoo_number(values[index])
        rows.append(row)
    rows = rows[-30:]
    if len(rows) != 30:
        raise ValueError("fewer_than_30_daily_rows")
    currency = str(meta.get("currency") or "").strip().upper()
    if not currency:
        raise ValueError("chart_currency_missing")
    previous_close = rows[-2]["close"]
    close = rows[-1]["close"]
    daily_change = close - previous_close
    daily_change_pct = (daily_change / previous_close * 100) if previous_close else None
    return rows, {
        "as_of": rows[-1]["date"],
        "currency": currency,
        "close": close,
        "daily_change": round(daily_change, 6),
        "daily_change_pct": (
            round(daily_change_pct, 4) if daily_change_pct is not None else None
        ),
    }


def _parse_yahoo_fx_chart(payload: object, from_currency: str) -> dict:
    """Parse an observed FX close without inventing or interpolating a rate."""

    if not isinstance(payload, dict):
        raise ValueError("fx_payload_invalid")
    chart = payload.get("chart")
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError("fx_result_missing")
    result = results[0]
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    quote = quotes[0] if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict) else None
    closes = quote.get("close") if isinstance(quote, dict) else None
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise ValueError("fx_series_missing")
    observed: list[tuple[int, float]] = []
    for raw_timestamp, raw_close in zip(timestamps, closes):
        timestamp = _safe_yahoo_number(raw_timestamp)
        close = _safe_yahoo_number(raw_close)
        if timestamp is None or close is None or close <= 0:
            continue
        observed.append((int(timestamp), close))
    if not observed:
        raise ValueError("fx_close_missing")
    timestamp, rate = observed[-1]
    quote_currency = str(meta.get("currency") or "").strip().upper()
    if quote_currency and quote_currency != "KRW":
        raise ValueError("fx_quote_currency_not_krw")
    return {
        "status": "observed",
        "provider": "yahoo_finance",
        "from_currency": str(from_currency).strip().upper(),
        "to_currency": "KRW",
        "rate": rate,
        "as_of": datetime.fromtimestamp(timestamp, UTC).date().isoformat(),
        "synthetic": False,
        "estimated": False,
        "ranking_effect": "none",
    }


def _yahoo_fx_to_krw(
    currency: str,
    *,
    observed_at: datetime,
    timeout: int,
    cache_ttl_seconds: int,
    request_headers: dict,
) -> dict:
    clean = str(currency or "").strip().upper()
    if clean == "KRW":
        return {
            "status": "observed",
            "provider": "identity",
            "from_currency": "KRW",
            "to_currency": "KRW",
            "rate": 1.0,
            "as_of": observed_at.date().isoformat(),
            "source_url": KRX_DATA_SOURCE_URL,
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        }
    try:
        symbol = _yahoo_fx_symbol_to_krw(clean)
    except ValueError:
        return {
            "status": "unavailable",
            "provider": "yahoo_finance",
            "from_currency": clean or None,
            "to_currency": "KRW",
            "rate": None,
            "as_of": None,
            "source_url": None,
            "reason": "unsupported_fx_currency",
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        }
    cache_key = f"FX:{clean}:KRW|{observed_at.date().isoformat()}"
    if cache_ttl_seconds:
        with _YAHOO_MARKET_CACHE_LOCK:
            cached = _YAHOO_MARKET_CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] < cache_ttl_seconds:
                return json.loads(json.dumps(cached[1]))
    encoded_symbol = urllib.parse.quote(symbol, safe=".-")
    source_url = YAHOO_PUBLIC_QUOTE_URL.format(symbol=encoded_symbol)
    chart_url = YAHOO_CHART_ENDPOINT.format(symbol=encoded_symbol) + "?" + urllib.parse.urlencode({
        "range": "10d",
        "interval": "1d",
        "events": "history",
    })
    try:
        result = _parse_yahoo_fx_chart(
            _json_request_with_retry(
                chart_url, headers=request_headers, timeout=timeout
            ),
            clean,
        )
        result["source_url"] = source_url
    except Exception as exc:
        result = {
            "status": "unavailable",
            "provider": "yahoo_finance",
            "from_currency": clean,
            "to_currency": "KRW",
            "rate": None,
            "as_of": None,
            "source_url": source_url,
            "reason": "fx_reference_unavailable",
            "error_type": type(exc).__name__,
            "http_status": getattr(exc, "code", None),
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        }
    if cache_ttl_seconds and result.get("status") == "observed":
        with _YAHOO_MARKET_CACHE_LOCK:
            _YAHOO_MARKET_CACHE[cache_key] = (
                time.monotonic(),
                json.loads(json.dumps(result)),
            )
    return result


def _yahoo_timeseries_values(
    payload: object,
    aliases: tuple[str, ...],
    *,
    positive: bool = False,
) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    timeseries = payload.get("timeseries")
    results = timeseries.get("result") if isinstance(timeseries, dict) else None
    if not isinstance(results, list):
        return []
    candidates: list[dict] = []
    seen: set[tuple] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        for priority, alias in enumerate(aliases):
            points = result.get(alias)
            if not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, dict):
                    continue
                reported = point.get("reportedValue")
                raw = reported.get("raw") if isinstance(reported, dict) else None
                value = _safe_yahoo_number(raw)
                if value is None or (positive and value <= 0):
                    continue
                as_of = str(point.get("asOfDate") or "").strip()
                try:
                    parsed_date = datetime.strptime(as_of, "%Y-%m-%d").date()
                except ValueError:
                    continue
                period_type = str(point.get("periodType") or "").strip() or None
                dedupe_key = (alias, as_of, period_type, value)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                candidates.append({
                    "value": value,
                    "as_of": as_of,
                    "period_type": period_type,
                    "type": alias,
                    "priority": priority,
                    "_date": parsed_date,
                })
    return candidates


def _latest_yahoo_timeseries_value(
    payload: object,
    aliases: tuple[str, ...],
    *,
    positive: bool = False,
    prefer_alias: bool = False,
) -> dict | None:
    candidates = _yahoo_timeseries_values(payload, aliases, positive=positive)
    if not candidates:
        return None
    if prefer_alias:
        preferred = min(item["priority"] for item in candidates)
        candidates = [item for item in candidates if item["priority"] == preferred]
    return max(candidates, key=lambda item: (item["as_of"], -item["priority"]))


def _yahoo_observation_provenance(observation: dict | None) -> dict | None:
    if not observation:
        return None
    return {
        "value": observation["value"],
        "type": observation["type"],
        "period_type": observation.get("period_type"),
        "as_of": observation["as_of"],
    }


def _roe_equity_denominator(payload: object, numerator: dict) -> dict | None:
    """Return a two-point average equity denominator near the income basis date."""

    if numerator.get("type") == "annualNetIncome":
        aliases = (
            "annualStockholdersEquity",
            "annualTotalStockholderEquity",
            "quarterlyStockholdersEquity",
            "quarterlyTotalStockholderEquity",
        )
    else:
        aliases = (
            "quarterlyStockholdersEquity",
            "quarterlyTotalStockholderEquity",
            "annualStockholdersEquity",
            "annualTotalStockholderEquity",
        )
    equities = _yahoo_timeseries_values(payload, aliases, positive=True)
    numerator_date = numerator.get("_date")
    if numerator_date is None:
        return None

    eligible_current = [
        item
        for item in equities
        if item["_date"] <= numerator_date
        and (numerator_date - item["_date"]).days <= 120
    ]
    if not eligible_current:
        return None
    current = max(
        eligible_current,
        key=lambda item: (item["_date"], -item["priority"]),
    )
    target_previous = current["_date"] - timedelta(days=365)
    eligible_previous = [
        item
        for item in equities
        if item["_date"] < current["_date"]
        and abs((item["_date"] - target_previous).days) <= 120
    ]
    if not eligible_previous:
        return None
    previous = min(
        eligible_previous,
        key=lambda item: (
            abs((item["_date"] - target_previous).days),
            item["priority"],
            -item["_date"].toordinal(),
        ),
    )
    average_equity = (current["value"] + previous["value"]) / 2
    if not math.isfinite(average_equity) or average_equity <= 0:
        return None
    return {
        "value": average_equity,
        "type": "averageStockholdersEquity",
        "period_type": "TWO_POINT_AVERAGE",
        "as_of": current["as_of"],
        "period_start": previous["as_of"],
        "period_end": current["as_of"],
        "observations": [
            _yahoo_observation_provenance(previous),
            _yahoo_observation_provenance(current),
        ],
    }


def _yahoo_observation_is_current(
    observation: dict | None,
    observed_at: datetime,
    *,
    max_age_days: int,
) -> bool:
    if not observation:
        return False
    as_of = observation.get("_date")
    if as_of is None:
        return False
    age = observed_at.astimezone(UTC).date() - as_of
    # A one-day lead is tolerated because Asian market dates can roll over
    # before the UTC collection day.  Larger future dates fail closed.
    return -1 <= age.days <= max_age_days


def _parse_yahoo_fundamentals(
    payload: object,
    *,
    observed_at: datetime | None = None,
) -> dict:
    reference_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
    market_cap = _latest_yahoo_timeseries_value(
        payload,
        ("trailingMarketCap", "quarterlyMarketCap"),
        positive=True,
    )
    reported_per = _latest_yahoo_timeseries_value(
        payload,
        ("trailingPeRatio",),
        positive=True,
    )
    equity = _latest_yahoo_timeseries_value(
        payload,
        (
            "quarterlyStockholdersEquity",
            "quarterlyTotalStockholderEquity",
            "annualStockholdersEquity",
            "annualTotalStockholderEquity",
        ),
        positive=True,
    )
    # Quarterly income is deliberately excluded.  A single quarter cannot be
    # labelled as annual ROE without an explicit annualisation policy.
    net_income = _latest_yahoo_timeseries_value(
        payload,
        ("trailingNetIncome", "annualNetIncome"),
        prefer_alias=True,
    )
    if not any((market_cap, reported_per, equity, net_income)):
        raise ValueError("required_fundamentals_missing")
    per = reported_per
    if net_income is not None and net_income["value"] <= 0:
        per = None
        per_status = "unavailable_loss_making"
    elif reported_per is None:
        per_status = "unavailable_not_reported"
    elif not _yahoo_observation_is_current(
        reported_per,
        reference_at,
        max_age_days=YAHOO_PER_FRESHNESS_DAYS,
    ):
        per = None
        per_status = "unavailable_stale"
    else:
        per_status = "observed"
    equity_value = equity["value"] if equity else None
    market_cap_value = market_cap["value"] if market_cap else None
    net_income_value = net_income["value"] if net_income else None
    pbr = (
        round(market_cap_value / equity_value, 4)
        if market_cap_value is not None and equity_value not in (None, 0)
        else None
    )
    roe_denominator = (
        _roe_equity_denominator(payload, net_income) if net_income else None
    )
    roe_pct = None
    roe_basis = None
    if net_income_value is not None and roe_denominator is not None:
        roe_pct = round(net_income_value / roe_denominator["value"] * 100, 4)
        roe_basis = (
            "trailing_net_income / average_two_point_stockholders_equity * 100"
            if net_income["type"] == "trailingNetIncome"
            else "annual_net_income / average_two_point_stockholders_equity * 100"
        )
    complete_values = (market_cap_value, pbr, roe_pct)
    # A missing current P/E is a valid reported state, not a reason to discard
    # the otherwise current market-cap/PBR/ROE snapshot.  Consumers must render
    # it as N/A and may never substitute the last historical positive value.
    per_is_complete = bool(
        per is not None
        or per_status in {
            "unavailable_loss_making",
            "unavailable_not_reported",
            "unavailable_stale",
        }
    )
    return {
        "status": "observed",
        "completeness": (
            "complete"
            if all(value is not None for value in complete_values) and per_is_complete
            else "partial"
        ),
        "market_cap": market_cap_value,
        "market_cap_as_of": market_cap["as_of"] if market_cap else None,
        "market_cap_type": market_cap["type"] if market_cap else None,
        "market_cap_period_type": market_cap.get("period_type") if market_cap else None,
        "per": round(per["value"], 4) if per else None,
        "per_status": per_status,
        "per_as_of": per["as_of"] if per else None,
        "per_type": per["type"] if per else None,
        "per_period_type": per.get("period_type") if per else None,
        "per_reported_as_of": reported_per["as_of"] if reported_per else None,
        "pbr": pbr,
        "pbr_as_of": market_cap["as_of"] if pbr is not None and market_cap else None,
        "pbr_type": "calculatedMarketCapToEquity" if pbr is not None else None,
        "pbr_period_type": "POINT_IN_TIME_OVER_REPORTED_EQUITY" if pbr is not None else None,
        "roe_pct": roe_pct,
        "roe_basis": roe_basis,
        "roe_calculated": roe_pct is not None,
        "roe_numerator": _yahoo_observation_provenance(net_income),
        "roe_denominator": roe_denominator,
        "equity": equity_value,
        "equity_as_of": (equity["as_of"] or None) if equity else None,
        "equity_period_type": (equity["period_type"] or None) if equity else None,
        "net_income": net_income_value,
        "net_income_as_of": (net_income["as_of"] or None) if net_income else None,
        "net_income_period_type": (net_income["period_type"] or None) if net_income else None,
        "calculation": {
            "pbr": "market_cap / latest_reported_equity",
            "roe_pct": roe_basis,
        },
    }


def _yahoo_fundamentals_url(symbol: str, observed_at: datetime) -> str:
    encoded_symbol = urllib.parse.quote(symbol, safe=".-")
    period2 = int((observed_at + timedelta(days=1)).timestamp())
    period1 = int((observed_at - timedelta(days=365 * 5)).timestamp())
    return (
        YAHOO_FUNDAMENTALS_ENDPOINT.format(symbol=encoded_symbol)
        + "?"
        + urllib.parse.urlencode(
            {
                "symbol": symbol,
                "type": ",".join(YAHOO_FUNDAMENTAL_TYPES),
                "period1": period1,
                "period2": period2,
                "merge": "false",
            },
            safe=",",
        )
    )


def _fetch_yahoo_fundamentals(
    symbol: str,
    *,
    observed_at: datetime,
    timeout: int,
    request_headers: dict,
) -> tuple[dict, str]:
    fundamentals_url = _yahoo_fundamentals_url(symbol, observed_at)
    payload = _json_request_with_retry(
        fundamentals_url,
        headers=request_headers,
        timeout=timeout,
    )
    return _parse_yahoo_fundamentals(
        payload,
        observed_at=observed_at,
    ), fundamentals_url


def _cache_yahoo_market_result(cache_key: str, result: dict) -> None:
    with _YAHOO_MARKET_CACHE_LOCK:
        _YAHOO_MARKET_CACHE[cache_key] = (
            time.monotonic(),
            json.loads(json.dumps(result)),
        )
        while len(_YAHOO_MARKET_CACHE) > YAHOO_MARKET_CACHE_MAX_ENTRIES:
            oldest_key = min(
                _YAHOO_MARKET_CACHE,
                key=lambda key: _YAHOO_MARKET_CACHE[key][0],
            )
            _YAHOO_MARKET_CACHE.pop(oldest_key, None)


def yahoo_finance_fundamentals(
    ticker: str,
    exchange: str,
    *,
    timeout: int = YAHOO_MARKET_TIMEOUT_SECONDS,
    cache_ttl_seconds: int = YAHOO_MARKET_CACHE_TTL_SECONDS,
    as_of: datetime | None = None,
) -> dict:
    """Return Yahoo fundamentals for a KRX listing without requiring a chart.

    The function is intended to supplement a pykrx price record.  It therefore
    returns no price rows, preserves Yahoo's reported dates and types, and uses
    an identity KRW conversion only for an observed native-KRW market cap.
    """

    clean_exchange = str(exchange or "").strip().upper()
    if clean_exchange not in {"KRX", "KOSPI", "KOSDAQ"}:
        return _yahoo_unavailable(
            ticker,
            exchange,
            "fundamentals_only_requires_krx_exchange",
        )
    try:
        symbol = yahoo_finance_symbol(ticker, clean_exchange)
    except ValueError as exc:
        return _yahoo_unavailable(ticker, exchange, str(exc))
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 30:
        return _yahoo_unavailable(ticker, exchange, "invalid_timeout", symbol=symbol)
    if (
        isinstance(cache_ttl_seconds, bool)
        or not isinstance(cache_ttl_seconds, int)
        or not 0 <= cache_ttl_seconds <= 86_400
    ):
        return _yahoo_unavailable(
            ticker,
            exchange,
            "invalid_cache_ttl",
            symbol=symbol,
        )
    observed_at = as_of or datetime.now(UTC)
    if observed_at.tzinfo is None:
        return _yahoo_unavailable(
            ticker,
            exchange,
            "as_of_must_be_timezone_aware",
            symbol=symbol,
        )
    observed_at = observed_at.astimezone(UTC)
    cache_key = f"FUNDAMENTALS:{symbol}|{observed_at.date().isoformat()}"
    if cache_ttl_seconds:
        with _YAHOO_MARKET_CACHE_LOCK:
            cached = _YAHOO_MARKET_CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] < cache_ttl_seconds:
                return json.loads(json.dumps(cached[1]))

    request_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; TRZIP/0.1; market-reference)",
    }
    try:
        valuation, fundamentals_url = _fetch_yahoo_fundamentals(
            symbol,
            observed_at=observed_at,
            timeout=timeout,
            request_headers=request_headers,
        )
    except Exception as exc:
        return _yahoo_unavailable(
            ticker,
            exchange,
            "fundamentals_unavailable",
            symbol=symbol,
            error_type=type(exc).__name__,
            http_status=getattr(exc, "code", None),
        )

    encoded_symbol = urllib.parse.quote(symbol, safe=".-")
    source_url = YAHOO_PUBLIC_QUOTE_URL.format(symbol=encoded_symbol)
    market_cap = _safe_yahoo_number(valuation.get("market_cap"))
    if market_cap is not None and market_cap <= 0:
        market_cap = None
    summary_dates = [
        valuation.get("market_cap_as_of"),
        valuation.get("per_as_of"),
        valuation.get("equity_as_of"),
        valuation.get("net_income_as_of"),
    ]
    summary_as_of = max((value for value in summary_dates if value), default=None)
    result = {
        "status": "observed",
        "provider": "yahoo_finance",
        "ticker": str(ticker).strip().upper(),
        "exchange": clean_exchange,
        "yahoo_symbol": symbol,
        "source_url": source_url,
        "source_urls": {
            "quote": source_url,
            "fundamentals": fundamentals_url,
        },
        "daily_ohlcv": [],
        "summary": {
            "as_of": summary_as_of,
            "currency": "KRW",
            "close": None,
            "daily_change": None,
            "daily_change_pct": None,
            "market_cap": market_cap,
            "close_krw": None,
            "market_cap_krw": market_cap,
        },
        "valuation": valuation,
        "fx_reference": {
            "status": "observed",
            "provider": "identity",
            "from_currency": "KRW",
            "to_currency": "KRW",
            "rate": 1.0,
            "as_of": valuation.get("market_cap_as_of") or summary_as_of,
            "source_url": source_url,
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        },
        "retrieved_at": observed_at.isoformat(),
        "data_mode": "observed_external",
        "synthetic": False,
        "estimated": False,
        "ranking_effect": "none",
        "relationship_evidence": False,
        "note": "Yahoo reported-fundamental supplement; no price chart and no relation evidence",
    }
    if (
        cache_ttl_seconds
        and valuation.get("completeness") == "complete"
        and result["summary"].get("market_cap_krw") is not None
    ):
        _cache_yahoo_market_result(cache_key, result)
    return result


def yahoo_finance_stock(
    ticker: str,
    exchange: str,
    *,
    timeout: int = YAHOO_MARKET_TIMEOUT_SECONDS,
    cache_ttl_seconds: int = YAHOO_MARKET_CACHE_TTL_SECONDS,
    as_of: datetime | None = None,
) -> dict:
    """Return fail-closed observed Yahoo market data for an overseas listing.

    Both Yahoo endpoints must return actual rows and reported fundamentals.
    Missing or malformed values are reported as ``unavailable``; no value is
    backfilled, inferred from a company name, or allowed to affect ranking.
    """

    try:
        symbol = yahoo_finance_symbol(ticker, exchange)
    except ValueError as exc:
        return _yahoo_unavailable(ticker, exchange, str(exc))
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 30:
        return _yahoo_unavailable(ticker, exchange, "invalid_timeout", symbol=symbol)
    if (
        isinstance(cache_ttl_seconds, bool)
        or not isinstance(cache_ttl_seconds, int)
        or not 0 <= cache_ttl_seconds <= 86_400
    ):
        return _yahoo_unavailable(
            ticker, exchange, "invalid_cache_ttl", symbol=symbol
        )
    observed_at = as_of or datetime.now(UTC)
    if observed_at.tzinfo is None:
        return _yahoo_unavailable(ticker, exchange, "as_of_must_be_timezone_aware", symbol=symbol)
    observed_at = observed_at.astimezone(UTC)
    cache_key = f"{symbol}|{observed_at.date().isoformat()}"
    if cache_ttl_seconds:
        with _YAHOO_MARKET_CACHE_LOCK:
            cached = _YAHOO_MARKET_CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] < cache_ttl_seconds:
                return json.loads(json.dumps(cached[1]))

    encoded_symbol = urllib.parse.quote(symbol, safe=".-")
    chart_url = YAHOO_CHART_ENDPOINT.format(symbol=encoded_symbol) + "?" + urllib.parse.urlencode({
        "range": "6mo",
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    })
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; TRZIP/0.1; market-reference)",
    }
    try:
        chart_payload = _json_request_with_retry(
            chart_url, headers=request_headers, timeout=timeout
        )
        rows, summary = _parse_yahoo_chart(chart_payload)
    except Exception as exc:
        return _yahoo_unavailable(
            ticker,
            exchange,
            "chart_unavailable",
            symbol=symbol,
            error_type=type(exc).__name__,
            http_status=getattr(exc, "code", None),
        )
    try:
        valuation, fundamentals_url = _fetch_yahoo_fundamentals(
            symbol,
            observed_at=observed_at,
            timeout=timeout,
            request_headers=request_headers,
        )
    except Exception as exc:
        return _yahoo_unavailable(
            ticker,
            exchange,
            "fundamentals_unavailable",
            symbol=symbol,
            error_type=type(exc).__name__,
            http_status=getattr(exc, "code", None),
        )

    summary["market_cap"] = valuation.get("market_cap")
    fx_reference = _yahoo_fx_to_krw(
        summary["currency"],
        observed_at=observed_at,
        timeout=timeout,
        cache_ttl_seconds=cache_ttl_seconds,
        request_headers=request_headers,
    )
    fx_rate = _safe_yahoo_number(fx_reference.get("rate"))
    if fx_reference.get("status") == "observed" and fx_rate is not None and fx_rate > 0:
        summary["close_krw"] = round(summary["close"] * fx_rate, 4)
        native_market_cap = _safe_yahoo_number(valuation.get("market_cap"))
        summary["market_cap_krw"] = (
            round(native_market_cap * fx_rate) if native_market_cap is not None else None
        )
    else:
        # The local-currency market record remains valid.  KRW display values
        # fail closed until an observed FX reference is available.
        summary["close_krw"] = None
        summary["market_cap_krw"] = None
    source_url = YAHOO_PUBLIC_QUOTE_URL.format(symbol=encoded_symbol)
    result = {
        "status": "observed",
        "provider": "yahoo_finance",
        "ticker": str(ticker).strip().upper(),
        "exchange": str(exchange).strip().upper(),
        "yahoo_symbol": symbol,
        "source_url": source_url,
        "source_urls": {
            "quote": source_url,
            "chart": chart_url,
            "fundamentals": fundamentals_url,
        },
        "daily_ohlcv": rows,
        "summary": summary,
        "valuation": valuation,
        "fx_reference": fx_reference,
        "retrieved_at": observed_at.isoformat(),
        "data_mode": "observed_external",
        "synthetic": False,
        "estimated": False,
        "ranking_effect": "none",
        "relationship_evidence": False,
        "note": "Yahoo daily and reported-fundamental reference; not realtime and not relation evidence",
    }
    if (
        cache_ttl_seconds
        and valuation.get("completeness") == "complete"
        and summary.get("close_krw") is not None
        and summary.get("market_cap_krw") is not None
    ):
        _cache_yahoo_market_result(cache_key, result)
    return result


def _scalar(value):
    return value.item() if hasattr(value, "item") else value


def _market_reaction(rows: list[dict]) -> dict:
    if len(rows) < 6:
        return {"status": "insufficient_history", "label": "시장 반응 판단 보류"}
    recent = rows[-5:]
    previous = rows[-10:-5] or rows[:-5]
    first_close = float(recent[0].get("close", recent[0].get("종가")) or 0)
    last_close = float(recent[-1].get("close", recent[-1].get("종가")) or 0)
    return_pct = ((last_close / first_close - 1) * 100) if first_close else None
    recent_volume = sum(float(row.get("volume", row.get("거래량")) or 0) for row in recent) / len(recent)
    previous_volume = sum(float(row.get("volume", row.get("거래량")) or 0) for row in previous) / len(previous) if previous else 0
    volume_ratio = recent_volume / previous_volume if previous_volume else None
    active = ((return_pct is not None and abs(return_pct) >= 5) or
              (volume_ratio is not None and volume_ratio >= 1.5))
    return {
        "status": "reaction_observed" if active else "limited_reaction",
        "label": "최근 시장 반응 관찰" if active else "최근 시장 반응 제한적",
        "five_session_return_pct": round(return_pct, 2) if return_pct is not None else None,
        "five_vs_previous_volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "warning": "일별 가격·거래량의 사후 참고값이며 트렌드 영향이나 향후 수익을 증명하지 않음",
    }


__all__ = (
    "clear_yahoo_market_cache",
    "enrich_company_identities",
    "integration_status",
    "krx_current_listing_verification",
    "opendart_company",
    "pykrx_stock",
    "yahoo_finance_fundamentals",
    "yahoo_finance_stock",
    "yahoo_finance_symbol",
)
