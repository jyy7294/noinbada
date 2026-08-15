from datetime import UTC, datetime, timedelta
import sys
import types
import xml.etree.ElementTree as ET

import pandas as pd

from trzip.company_adapters import (
    OHLCV_COLUMNS,
    KRX_DATA_SOURCE_URL,
    _market_reaction,
    _public_opendart_identity,
    enrich_company_identities,
    opendart_company,
    pykrx_stock,
)


def test_pykrx_columns_have_stable_frontend_names():
    assert OHLCV_COLUMNS["종가"] == "close"
    assert OHLCV_COLUMNS["거래량"] == "volume"


def test_pykrx_reference_includes_30_day_chart_valuation_and_public_source(monkeypatch):
    dates = pd.date_range("2026-06-30", periods=35, freq="B")
    ohlcv = pd.DataFrame(
        {
            "시가": range(100, 135), "고가": range(101, 136),
            "저가": range(99, 134), "종가": range(100, 135),
            "거래량": [1000] * 35, "거래대금": [100000] * 35,
            "등락률": [0.5] * 35,
        },
        index=dates,
    )
    fundamentals = pd.DataFrame(
        {"BPS": [50000], "PER": [12.3], "PBR": [1.4], "EPS": [4000], "DIV": [2.1], "DPS": [800]},
        index=[dates[-1]],
    )
    market_cap = pd.DataFrame({"시가총액": [123_000_000_000]}, index=[dates[-1]])
    fake_stock = types.SimpleNamespace(
        get_market_ticker_name=lambda _code: "검증기업",
        get_market_ohlcv_by_date=lambda *_args: ohlcv,
        get_market_fundamental_by_date=lambda *_args: fundamentals,
        get_market_cap_by_date=lambda *_args: market_cap,
    )
    monkeypatch.setitem(sys.modules, "pykrx", types.SimpleNamespace(stock=fake_stock))

    result = pykrx_stock("005930", "20260815")

    assert result["status"] == "observed"
    assert result["source_url"] == KRX_DATA_SOURCE_URL
    assert len(result["daily_ohlcv"]) == 30
    assert result["valuation"]["per"] == 12.3
    assert result["valuation"]["pbr"] == 1.4
    assert result["summary"]["market_cap"] == 123_000_000_000
    assert result["summary"]["market_cap_krw"] == 123_000_000_000
    assert result["summary"]["close_krw"] == 134
    assert result["fx_reference"]["rate"] == 1.0
    assert result["fx_reference"]["to_currency"] == "KRW"


def test_market_reaction_detects_price_or_volume_change():
    rows = []
    for index in range(10):
        rows.append({
            "날짜": f"2026-08-{index + 1:02d}",
            "종가": 100 + index * 2,
            "거래량": 100 if index < 5 else 220,
        })

    result = _market_reaction(rows)

    assert result["status"] == "reaction_observed"
    assert result["five_vs_previous_volume_ratio"] == 2.2
    assert "향후 수익" in result["warning"]


def test_public_opendart_identity_excludes_personal_and_credential_fields():
    at = datetime(2026, 8, 13, 0, tzinfo=UTC)
    payload = _public_opendart_identity(
        {
            "status": "verified",
            "stock_code": "005930",
            "overview": {
                "corp_name": "삼성전자주식회사",
                "corp_name_eng": "Samsung Electronics Co., Ltd.",
                "stock_name": "삼성전자",
                "stock_code": "005930",
                "corp_cls": "Y",
                "hm_url": "www.samsung.com/sec",
                "est_dt": "19690113",
                "ceo_nm": "공개 출력 제외",
                "adres": "공개 출력 제외",
            },
        },
        company_name="삼성전자",
        stock_code="005930",
        observed_at=at,
    )

    assert payload["status"] == "verified"
    assert payload["legal_name"] == "삼성전자주식회사"
    assert payload["homepage"] == "https://www.samsung.com/sec"
    assert payload["ranking_effect"] == "none"
    assert payload["relationship_evidence"] is False
    assert "ceo_nm" not in payload and "adres" not in payload


def test_opendart_company_prefers_stock_code_over_display_name(monkeypatch):
    root = ET.fromstring(
        """<result><list><corp_code>00126380</corp_code>
        <corp_name>삼성전자</corp_name><stock_code>005930</stock_code>
        <modify_date>20260813</modify_date></list></result>"""
    )
    monkeypatch.setenv("OPENDART_API_KEY", "configured-in-test-only")
    monkeypatch.setattr("trzip.company_adapters._opendart_corp_root", lambda _key: root)
    monkeypatch.setattr(
        "trzip.company_adapters._json_request",
        lambda _url: {
            "status": "000",
            "corp_name": "삼성전자(주)",
            "stock_name": "삼성전자",
            "stock_code": "005930",
        },
    )

    result = opendart_company("삼성전자 보통주", stock_code="005930")

    assert result["status"] == "verified"
    assert result["stock_code"] == "005930"


def test_company_identity_cache_reuses_verified_record(monkeypatch, tmp_path):
    monkeypatch.delenv("TRZIP_DISABLE_EXTERNAL_COMPANY_IDENTITY", raising=False)
    calls = []

    def fake_company(company_name, stock_code=None):
        calls.append((company_name, stock_code))
        return {
            "status": "verified",
            "stock_code": "005930",
            "overview": {
                "corp_name": "삼성전자주식회사",
                "corp_name_eng": "Samsung Electronics Co., Ltd.",
                "stock_name": "삼성전자",
                "stock_code": "005930",
                "corp_cls": "Y",
                "hm_url": "https://www.samsung.com/sec",
                "est_dt": "19690113",
            },
        }

    monkeypatch.setattr("trzip.company_adapters.opendart_company", fake_company)
    companies = [{"company": "삼성전자", "stock_code": "005930"}]
    at = datetime(2026, 8, 13, 0, tzinfo=UTC)
    first, first_status = enrich_company_identities(
        companies, database_path=tmp_path / "identity.sqlite3", observed_at=at
    )
    second, second_status = enrich_company_identities(
        companies,
        database_path=tmp_path / "identity.sqlite3",
        observed_at=at + timedelta(hours=1),
    )

    assert calls == [("삼성전자", "005930")]
    assert first["005930"]["status"] == second["005930"]["status"] == "verified"
    assert first_status["fetched"] == 1 and first_status["reused"] == 0
    assert second_status["fetched"] == 0 and second_status["reused"] == 1


def test_company_identity_cache_recovers_from_corrupt_row(monkeypatch, tmp_path):
    import sqlite3

    monkeypatch.delenv("TRZIP_DISABLE_EXTERNAL_COMPANY_IDENTITY", raising=False)
    database_path = tmp_path / "identity.sqlite3"
    at = datetime(2026, 8, 13, 0, tzinfo=UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE company_identity_cache (
                   stock_code TEXT PRIMARY KEY,
                   company_name TEXT NOT NULL,
                   status TEXT NOT NULL,
                   payload_json TEXT NOT NULL,
                   observed_at TEXT NOT NULL
               )"""
        )
        connection.execute(
            "INSERT INTO company_identity_cache VALUES (?,?,?,?,?)",
            ("005930", "삼성전자", "verified", "{broken", at.isoformat()),
        )
        connection.commit()

    calls = []

    def fake_company(company_name, stock_code=None):
        calls.append((company_name, stock_code))
        return {
            "status": "verified",
            "stock_code": stock_code,
            "overview": {
                "corp_name": company_name,
                "stock_code": stock_code,
            },
        }

    monkeypatch.setattr("trzip.company_adapters.opendart_company", fake_company)
    identities, status = enrich_company_identities(
        [{"company": "삼성전자", "stock_code": "005930"}],
        database_path=database_path,
        observed_at=at + timedelta(hours=1),
    )

    assert calls == [("삼성전자", "005930")]
    assert identities["005930"]["status"] == "verified"
    assert status["fetched"] == 1 and status["reused"] == 0
