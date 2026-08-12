from __future__ import annotations

import io
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from functools import lru_cache

from .hourly_store import load_local_env


def integration_status() -> dict:
    load_local_env()
    return {
        "opendart": {"configured": bool(os.environ.get("OPENDART_API_KEY", "").strip()),
                     "role": "issuer identity, company overview and filing evidence"},
        "pykrx": {"configured": True,
                  "role": "Korean ticker name and daily OHLCV reference; never realtime quote or trend ranking"},
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


def opendart_company(company_name: str) -> dict:
    """Resolve an exact Korean company name and return OpenDART company overview."""
    load_local_env()
    key = os.environ.get("OPENDART_API_KEY", "").strip()
    if not key:
        return {"status": "unavailable", "company": company_name, "reason": "OPENDART_API_KEY not configured"}
    try:
        root = _opendart_corp_root(key)
        def normalize_issuer(value: str) -> str:
            compact = re.sub(r"\s+", "", value).casefold()
            return re.sub(r"(?:\(주\)|㈜|주식회사)$", "", compact)
        target = normalize_issuer(company_name)
        matches = []
        for node in root.findall("list"):
            name = (node.findtext("corp_name") or "").strip()
            if normalize_issuer(name) == target:
                matches.append({child.tag: (child.text or "").strip() for child in node})
        if not matches:
            return {"status": "not_found", "company": company_name, "reason": "exact OpenDART issuer name not found"}
        match = sorted(matches, key=lambda item: bool(item.get("stock_code")), reverse=True)[0]
        overview_query = urllib.parse.urlencode({"crtfc_key": key, "corp_code": match["corp_code"]})
        overview = _json_request("https://opendart.fss.or.kr/api/company.json?" + overview_query)
        if overview.get("status") != "000":
            return {"status": "error", "company": company_name, "reason": overview.get("message", "OpenDART error")}
        return {"status": "verified", "company": company_name, "corp_code": match["corp_code"],
                "stock_code": match.get("stock_code") or None, "modify_date": match.get("modify_date"),
                "overview": {key: overview.get(key) for key in ("corp_name", "corp_name_eng", "stock_name", "stock_code", "ceo_nm", "corp_cls", "adres", "hm_url", "est_dt")}}
    except Exception as exc:
        return {"status": "error", "company": company_name, "reason": f"{type(exc).__name__}: {exc}"}


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
            rows.append({"date": at.strftime("%Y-%m-%d"), **{str(key): _scalar(value) for key, value in values.items()}})
        if not name and not rows:
            return {"status": "not_found", "stock_code": code, "reason": "pykrx returned no ticker or OHLCV"}
        reaction = _market_reaction(rows)
        return {"status": "observed", "provider": "pykrx", "stock_code": code,
                "name": name or None, "daily_ohlcv": rows,
                "latest_daily": rows[-1] if rows else None,
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
    first_close = float(recent[0].get("종가") or 0)
    last_close = float(recent[-1].get("종가") or 0)
    return_pct = ((last_close / first_close - 1) * 100) if first_close else None
    recent_volume = sum(float(row.get("거래량") or 0) for row in recent) / len(recent)
    previous_volume = sum(float(row.get("거래량") or 0) for row in previous) / len(previous) if previous else 0
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


@lru_cache(maxsize=128)
def company_profile(company_name: str, stock_code: str) -> dict:
    """Combine issuer identity and daily market reference without forecasting."""
    dart = opendart_company(company_name)
    market = pykrx_stock(stock_code)
    return {
        "company": company_name,
        "stock_code": stock_code,
        "official_identity": dart,
        "market_reference": market,
        "evidence_summary": {
            "dart_verified": dart.get("status") == "verified",
            "market_observed": market.get("status") == "observed",
        },
        "interpretation_policy": {
            "allowed": ["사업 관계", "상장 여부", "현재 시장지표", "공식 위험요인"],
            "prohibited": ["확정 수혜", "주가 상승 보장", "근거 없는 테마주 연결"],
        },
    }
