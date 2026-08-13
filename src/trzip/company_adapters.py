from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

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


def pykrx_stock(stock_code: str, base_date: str | None = None, lookback_days: int = 14) -> dict:
    """Return a Korean ticker name and recent daily OHLCV through pykrx.

    This adapter intentionally does not describe the last daily row as a realtime
    quote and does not use it to prove a trend-company relationship.
    """
    code = stock_code.strip()
    if len(code) != 6 or not code.isdigit():
        return {"status": "invalid", "stock_code": stock_code, "reason": "six-digit stock code required"}
    end = datetime.strptime(base_date, "%Y%m%d") if base_date else datetime.now()
    start = end - timedelta(days=max(7, min(lookback_days, 90)))
    try:
        from contextlib import redirect_stderr, redirect_stdout
        quiet = io.StringIO()
        with redirect_stdout(quiet), redirect_stderr(quiet):
            from pykrx import stock
            name = stock.get_market_ticker_name(code)
            frame = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
        rows = []
        for at, values in frame.tail(10).iterrows():
            normalized = {
                OHLCV_COLUMNS.get(str(key), str(key)): _scalar(value)
                for key, value in values.items()
            }
            rows.append({"date": at.strftime("%Y-%m-%d"), **normalized})
        if not name and not rows:
            return {"status": "not_found", "stock_code": code, "reason": "pykrx returned no ticker or OHLCV"}
        reaction = _market_reaction(rows)
        latest = rows[-1] if rows else None
        previous = rows[-2] if len(rows) > 1 else None
        close = float(latest.get("close") or 0) if latest else 0
        previous_close = float(previous.get("close") or 0) if previous else 0
        daily_change_pct = (
            round((close / previous_close - 1) * 100, 2)
            if close and previous_close else None
        )
        return {"status": "observed", "provider": "pykrx", "stock_code": code,
                "name": name or None, "daily_ohlcv": rows,
                "latest_daily": latest,
                "summary": {
                    "as_of": latest.get("date") if latest else None,
                    "close": int(close) if close else None,
                    "daily_change_pct": daily_change_pct,
                    "volume": int(latest.get("volume") or 0) if latest else None,
                },
                "market_reaction": reaction,
                "note": "daily reference data; not realtime, not a forecast, and not relation evidence"}
    except Exception as exc:
        return {"status": "error", "stock_code": code, "reason": f"{type(exc).__name__}: {exc}"}


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
    "enrich_company_identities",
    "integration_status",
    "opendart_company",
    "pykrx_stock",
)
