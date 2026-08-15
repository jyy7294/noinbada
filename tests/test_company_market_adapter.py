from datetime import UTC, datetime, timedelta

import pytest

from trzip.company_adapters import (
    clear_yahoo_market_cache,
    yahoo_finance_fundamentals,
    yahoo_finance_stock,
    yahoo_finance_symbol,
)


@pytest.fixture(autouse=True)
def _empty_yahoo_cache():
    clear_yahoo_market_cache()
    yield
    clear_yahoo_market_cache()


def _chart_payload(rows: int = 35) -> dict:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    timestamps = [int((start + timedelta(days=index)).timestamp()) for index in range(rows)]
    closes = [100.0 + index for index in range(rows)]
    return {
        "chart": {
            "result": [{
                "meta": {"symbol": "AAPL", "currency": "USD"},
                "timestamp": timestamps,
                "indicators": {
                    "quote": [{
                        "open": [value - 1 for value in closes],
                        "high": [value + 1 for value in closes],
                        "low": [value - 2 for value in closes],
                        "close": closes,
                        "volume": [1_000_000 + index for index in range(rows)],
                    }]
                },
            }],
            "error": None,
        }
    }


def _series_points(name: str, points: list[tuple[float, str, str]]) -> dict:
    return {
        "meta": {"symbol": ["AAPL"], "type": [name]},
        name: [
            {
                "asOfDate": as_of,
                "periodType": period_type,
                "reportedValue": {"raw": value, "fmt": str(value)},
            }
            for value, as_of, period_type in points
        ],
    }


def _series(name: str, value: float, as_of: str, period_type: str = "TTM") -> dict:
    return _series_points(name, [(value, as_of, period_type)])


def _fundamentals_payload(*, include_per: bool = True) -> dict:
    result = [
        _series("trailingMarketCap", 250_000_000_000, "2026-08-14"),
        _series_points(
            "quarterlyStockholdersEquity",
            [
                (100_000_000_000, "2025-06-30", "3M"),
                (100_000_000_000, "2026-06-30", "3M"),
            ],
        ),
        _series("trailingNetIncome", 20_000_000_000, "2026-06-30", "TTM"),
    ]
    if include_per:
        result.append(_series("trailingPeRatio", 18.25, "2026-08-14"))
    return {"timeseries": {"result": result, "error": None}}


def _fx_payload(rate: float = 1_350.5) -> dict:
    at = datetime(2026, 8, 14, tzinfo=UTC)
    return {
        "chart": {
            "result": [{
                "meta": {"symbol": "KRW=X", "currency": "KRW"},
                "timestamp": [int(at.timestamp())],
                "indicators": {"quote": [{"close": [rate]}]},
            }],
            "error": None,
        }
    }


@pytest.mark.parametrize(
    ("ticker", "exchange", "expected"),
    [
        ("AAPL", "NASDAQ", "AAPL"),
        ("ADS", "NYSE", "ADS"),
        ("7203", "TSE", "7203.T"),
        ("700", "HKEX", "0700.HK"),
        ("005930", "KOSPI", "005930.KS"),
        ("267980", "KOSDAQ", "267980.KQ"),
        ("005930", "KRX", "005930.KS"),
    ],
)
def test_yahoo_symbol_mapping_is_exchange_specific(ticker, exchange, expected):
    assert yahoo_finance_symbol(ticker, exchange) == expected


@pytest.mark.parametrize(
    ("ticker", "exchange"),
    [
        ("AAPL", "KRX"),
        ("07000", "HKEX"),
        ("7203.T", "TSE"),
        ("AAPL/../../", "NASDAQ"),
    ],
)
def test_yahoo_symbol_mapping_rejects_unsupported_or_unsafe_input(ticker, exchange):
    with pytest.raises(ValueError):
        yahoo_finance_symbol(ticker, exchange)


def test_yahoo_adapter_returns_30_observed_rows_and_reported_ratios(monkeypatch):
    requested = []

    def fake_json_request(url, **kwargs):
        requested.append((url, kwargs))
        if "fundamentals-timeseries" in url:
            return _fundamentals_payload()
        if "KRW%3DX" in url:
            return _fx_payload()
        return _chart_payload()

    monkeypatch.setattr("trzip.company_adapters._json_request", fake_json_request)
    observed_at = datetime(2026, 8, 15, 0, tzinfo=UTC)

    result = yahoo_finance_stock("AAPL", "NASDAQ", as_of=observed_at)

    assert result["status"] == "observed"
    assert result["provider"] == "yahoo_finance"
    assert result["yahoo_symbol"] == "AAPL"
    assert result["source_url"] == "https://finance.yahoo.com/quote/AAPL"
    assert len(result["daily_ohlcv"]) == 30
    assert result["summary"] == {
        "as_of": "2026-07-05",
        "currency": "USD",
        "close": 134.0,
        "daily_change": 1.0,
        "daily_change_pct": pytest.approx(0.7519),
        "market_cap": 250_000_000_000.0,
        "close_krw": pytest.approx(180_967.0),
        "market_cap_krw": 337_625_000_000_000,
    }
    assert result["fx_reference"] == {
        "status": "observed",
        "provider": "yahoo_finance",
        "from_currency": "USD",
        "to_currency": "KRW",
        "rate": 1_350.5,
        "as_of": "2026-08-14",
        "synthetic": False,
        "estimated": False,
        "ranking_effect": "none",
        "source_url": "https://finance.yahoo.com/quote/KRW%3DX",
    }
    assert result["valuation"]["per"] == 18.25
    assert result["valuation"]["per_as_of"] == "2026-08-14"
    assert result["valuation"]["per_type"] == "trailingPeRatio"
    assert result["valuation"]["market_cap_as_of"] == "2026-08-14"
    assert result["valuation"]["market_cap_type"] == "trailingMarketCap"
    assert result["valuation"]["pbr"] == 2.5
    assert result["valuation"]["roe_pct"] == 20.0
    assert result["valuation"]["roe_calculated"] is True
    assert result["valuation"]["roe_basis"] == (
        "trailing_net_income / average_two_point_stockholders_equity * 100"
    )
    assert result["valuation"]["roe_numerator"] == {
        "value": 20_000_000_000.0,
        "type": "trailingNetIncome",
        "period_type": "TTM",
        "as_of": "2026-06-30",
    }
    assert result["valuation"]["roe_denominator"]["value"] == 100_000_000_000
    assert result["valuation"]["roe_denominator"]["period_start"] == "2025-06-30"
    assert result["valuation"]["roe_denominator"]["period_end"] == "2026-06-30"
    assert result["valuation"]["calculation"] == {
        "pbr": "market_cap / latest_reported_equity",
        "roe_pct": "trailing_net_income / average_two_point_stockholders_equity * 100",
    }
    assert result["synthetic"] is False
    assert result["estimated"] is False
    assert result["ranking_effect"] == "none"
    assert result["relationship_evidence"] is False
    assert len(requested) == 3
    assert all(call[1]["timeout"] == 8 for call in requested)


def test_yahoo_roe_never_uses_quarterly_net_income(monkeypatch):
    payload = {
        "timeseries": {
            "result": [
                _series("trailingMarketCap", 250_000_000_000, "2026-08-14"),
                _series_points(
                    "quarterlyStockholdersEquity",
                    [
                        (100_000_000_000, "2025-06-30", "3M"),
                        (100_000_000_000, "2026-06-30", "3M"),
                    ],
                ),
                _series("quarterlyNetIncome", 30_000_000_000, "2026-06-30", "3M"),
            ],
            "error": None,
        }
    }
    requested = []

    def fake_json_request(url, **_kwargs):
        requested.append(url)
        return payload

    monkeypatch.setattr("trzip.company_adapters._json_request", fake_json_request)

    result = yahoo_finance_fundamentals(
        "005930",
        "KOSPI",
        cache_ttl_seconds=0,
        as_of=datetime(2026, 8, 15, tzinfo=UTC),
    )

    assert result["status"] == "observed"
    assert result["valuation"]["roe_pct"] is None
    assert result["valuation"]["roe_calculated"] is False
    assert result["valuation"]["roe_numerator"] is None
    assert "quarterlyNetIncome" not in requested[0]


def test_yahoo_roe_prefers_ttm_over_newer_quarterly_and_uses_average_equity(monkeypatch):
    payload = {
        "timeseries": {
            "result": [
                _series("trailingMarketCap", 250_000_000_000, "2026-08-14"),
                _series("trailingPeRatio", 18.25, "2026-08-14"),
                _series_points(
                    "quarterlyStockholdersEquity",
                    [
                        (80_000_000_000, "2025-06-30", "3M"),
                        (120_000_000_000, "2026-06-30", "3M"),
                    ],
                ),
                _series("trailingNetIncome", 20_000_000_000, "2026-06-30", "TTM"),
                _series("quarterlyNetIncome", 90_000_000_000, "2026-09-30", "3M"),
            ],
            "error": None,
        }
    }

    monkeypatch.setattr(
        "trzip.company_adapters._json_request",
        lambda _url, **_kwargs: payload,
    )

    result = yahoo_finance_fundamentals(
        "005930", "KOSPI", cache_ttl_seconds=0
    )
    valuation = result["valuation"]

    assert valuation["roe_pct"] == 20.0
    assert valuation["roe_numerator"] == {
        "value": 20_000_000_000.0,
        "type": "trailingNetIncome",
        "period_type": "TTM",
        "as_of": "2026-06-30",
    }
    assert valuation["roe_denominator"] == {
        "value": 100_000_000_000.0,
        "type": "averageStockholdersEquity",
        "period_type": "TWO_POINT_AVERAGE",
        "as_of": "2026-06-30",
        "period_start": "2025-06-30",
        "period_end": "2026-06-30",
        "observations": [
            {
                "value": 80_000_000_000.0,
                "type": "quarterlyStockholdersEquity",
                "period_type": "3M",
                "as_of": "2025-06-30",
            },
            {
                "value": 120_000_000_000.0,
                "type": "quarterlyStockholdersEquity",
                "period_type": "3M",
                "as_of": "2026-06-30",
            },
        ],
    }


def test_yahoo_roe_uses_annual_fallback(monkeypatch):
    payload = {
        "timeseries": {
            "result": [
                _series("trailingMarketCap", 250_000_000_000, "2026-01-15"),
                _series("trailingPeRatio", 18.25, "2026-01-15"),
                _series_points(
                    "annualStockholdersEquity",
                    [
                        (80_000_000_000, "2024-12-31", "12M"),
                        (120_000_000_000, "2025-12-31", "12M"),
                    ],
                ),
                _series("annualNetIncome", 12_000_000_000, "2025-12-31", "12M"),
            ],
            "error": None,
        }
    }
    monkeypatch.setattr(
        "trzip.company_adapters._json_request",
        lambda _url, **_kwargs: payload,
    )

    result = yahoo_finance_fundamentals(
        "267980", "KOSDAQ", cache_ttl_seconds=0
    )

    assert result["valuation"]["roe_pct"] == 12.0
    assert result["valuation"]["roe_basis"] == (
        "annual_net_income / average_two_point_stockholders_equity * 100"
    )
    assert result["valuation"]["roe_numerator"]["type"] == "annualNetIncome"
    assert result["valuation"]["roe_denominator"]["period_start"] == "2024-12-31"


def test_yahoo_roe_fails_closed_without_two_equity_observations(monkeypatch):
    payload = {
        "timeseries": {
            "result": [
                _series("trailingMarketCap", 250_000_000_000, "2026-08-14"),
                _series("quarterlyStockholdersEquity", 100_000_000_000, "2026-06-30", "3M"),
                _series("trailingNetIncome", 20_000_000_000, "2026-06-30", "TTM"),
            ],
            "error": None,
        }
    }
    monkeypatch.setattr(
        "trzip.company_adapters._json_request",
        lambda _url, **_kwargs: payload,
    )

    result = yahoo_finance_fundamentals(
        "005930", "KOSPI", cache_ttl_seconds=0
    )

    assert result["valuation"]["roe_pct"] is None
    assert result["valuation"]["roe_calculated"] is False
    assert result["valuation"]["roe_numerator"]["type"] == "trailingNetIncome"
    assert result["valuation"]["roe_denominator"] is None


@pytest.mark.parametrize(("income", "expected_roe"), [(0, 0.0), (-10_000_000_000, -10.0)])
def test_yahoo_invalid_ratios_are_null_but_zero_or_negative_roe_is_valid(
    monkeypatch, income, expected_roe
):
    payload = {
        "timeseries": {
            "result": [
                _series("trailingMarketCap", 0, "2026-08-14"),
                _series("quarterlyMarketCap", float("inf"), "2026-08-14"),
                _series("trailingPeRatio", float("nan"), "2026-08-14"),
                _series_points(
                    "quarterlyStockholdersEquity",
                    [
                        (100_000_000_000, "2025-06-30", "3M"),
                        (100_000_000_000, "2026-06-30", "3M"),
                    ],
                ),
                _series("trailingNetIncome", income, "2026-06-30", "TTM"),
            ],
            "error": None,
        }
    }
    monkeypatch.setattr(
        "trzip.company_adapters._json_request",
        lambda _url, **_kwargs: payload,
    )

    result = yahoo_finance_fundamentals(
        "005930", "KOSPI", cache_ttl_seconds=0
    )

    assert result["summary"]["market_cap"] is None
    assert result["summary"]["market_cap_krw"] is None
    assert result["valuation"]["market_cap"] is None
    assert result["valuation"]["per"] is None
    assert result["valuation"]["pbr"] is None
    assert result["valuation"]["roe_pct"] == expected_roe
    assert result["valuation"]["roe_calculated"] is True


@pytest.mark.parametrize(
    ("ticker", "exchange", "expected_symbol"),
    [
        ("005930", "KOSPI", "005930.KS"),
        ("267980", "KOSDAQ", "267980.KQ"),
    ],
)
def test_yahoo_fundamentals_only_succeeds_without_a_30_day_chart(
    monkeypatch, ticker, exchange, expected_symbol
):
    calls = []

    def fake_json_request(url, **_kwargs):
        calls.append(url)
        if "finance/chart" in url:
            return _chart_payload(rows=2)
        return _fundamentals_payload()

    monkeypatch.setattr("trzip.company_adapters._json_request", fake_json_request)

    result = yahoo_finance_fundamentals(
        ticker,
        exchange,
        cache_ttl_seconds=0,
        as_of=datetime(2026, 8, 15, tzinfo=UTC),
    )

    assert result["status"] == "observed"
    assert result["yahoo_symbol"] == expected_symbol
    assert result["daily_ohlcv"] == []
    assert result["summary"]["currency"] == "KRW"
    assert result["summary"]["market_cap_krw"] == 250_000_000_000
    assert result["fx_reference"]["provider"] == "identity"
    assert result["fx_reference"]["rate"] == 1.0
    assert set(result["source_urls"]) == {"quote", "fundamentals"}
    assert len(calls) == 1
    assert "finance/chart" not in calls[0]


def test_yahoo_adapter_uses_bounded_success_cache(monkeypatch):
    calls = []

    def fake_json_request(url, **_kwargs):
        calls.append(url)
        if "fundamentals-timeseries" in url:
            return _fundamentals_payload()
        if "HKDKRW%3DX" in url:
            return _fx_payload(175.0)
        return _chart_payload()

    monkeypatch.setattr("trzip.company_adapters._json_request", fake_json_request)
    observed_at = datetime(2026, 8, 15, 0, tzinfo=UTC)

    first = yahoo_finance_stock("700", "HKEX", as_of=observed_at)
    second = yahoo_finance_stock("700", "HKEX", as_of=observed_at)
    second["summary"]["close"] = -1
    third = yahoo_finance_stock("700", "HKEX", as_of=observed_at)

    assert first["status"] == second["status"] == third["status"] == "observed"
    assert first["yahoo_symbol"] == "0700.HK"
    assert third["summary"]["close"] == 134.0
    assert len(calls) == 3


def test_yahoo_adapter_fails_closed_on_transport_or_missing_fundamentals(monkeypatch):
    def timeout_request(_url, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("trzip.company_adapters._json_request", timeout_request)
    timed_out = yahoo_finance_stock("7203", "TSE", cache_ttl_seconds=0)

    assert timed_out["status"] == "unavailable"
    assert timed_out["reason"] == "chart_unavailable"
    assert timed_out["error_type"] == "TimeoutError"
    assert timed_out["daily_ohlcv"] == []
    assert timed_out["summary"]["close"] is None
    assert timed_out["synthetic"] is False
    assert timed_out["estimated"] is False
    assert timed_out["ranking_effect"] == "none"

    calls = []

    def missing_per_request(url, **_kwargs):
        calls.append(url)
        return _chart_payload() if "finance/chart" in url else _fundamentals_payload(include_per=False)

    monkeypatch.setattr("trzip.company_adapters._json_request", missing_per_request)
    missing = yahoo_finance_stock("AAPL", "NASDAQ", cache_ttl_seconds=0)

    assert missing["status"] == "observed"
    assert missing["valuation"]["completeness"] == "partial"
    assert missing["valuation"]["per"] is None
    assert missing["valuation"]["pbr"] == 2.5
    assert missing["valuation"]["roe_pct"] == 20.0
    assert missing["summary"]["market_cap"] == 250_000_000_000.0
    assert missing["summary"]["market_cap_krw"] is None
    assert len(calls) == 3


def test_yahoo_adapter_keeps_native_market_data_but_never_fakes_krw_when_fx_fails(monkeypatch):
    def fake_json_request(url, **_kwargs):
        if "fundamentals-timeseries" in url:
            return _fundamentals_payload()
        if "KRW%3DX" in url:
            raise TimeoutError("simulated fx timeout")
        return _chart_payload()

    monkeypatch.setattr("trzip.company_adapters._json_request", fake_json_request)

    result = yahoo_finance_stock("AAPL", "NASDAQ", cache_ttl_seconds=0)

    assert result["status"] == "observed"
    assert result["summary"]["currency"] == "USD"
    assert result["summary"]["market_cap"] == 250_000_000_000.0
    assert result["summary"]["market_cap_krw"] is None
    assert result["summary"]["close_krw"] is None
    assert result["fx_reference"]["status"] == "unavailable"
    assert result["fx_reference"]["synthetic"] is False


def test_yahoo_adapter_validates_inputs_without_network(monkeypatch):
    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("network must not be called")

    monkeypatch.setattr("trzip.company_adapters._json_request", unexpected_request)

    unsupported = yahoo_finance_stock("AAPL", "KRX")
    unsafe = yahoo_finance_stock("AAPL/../../", "NASDAQ")
    bad_timeout = yahoo_finance_stock("AAPL", "NASDAQ", timeout=0)
    bad_cache = yahoo_finance_stock("AAPL", "NASDAQ", cache_ttl_seconds=-1)
    naive_date = yahoo_finance_stock(
        "AAPL", "NASDAQ", as_of=datetime(2026, 8, 15)
    )

    assert unsupported["reason"] == "invalid_krx_ticker"
    assert unsafe["reason"] == "invalid_ticker"
    assert bad_timeout["reason"] == "invalid_timeout"
    assert bad_cache["reason"] == "invalid_cache_ttl"
    assert naive_date["reason"] == "as_of_must_be_timezone_aware"
    assert all(
        item["status"] == "unavailable"
        for item in (unsupported, unsafe, bad_timeout, bad_cache, naive_date)
    )


def test_yahoo_adapter_supports_actual_krx_fundamentals_without_fx_request(monkeypatch):
    calls = []

    def fake_json_request(url, **_kwargs):
        calls.append(url)
        if "fundamentals-timeseries" in url:
            return _fundamentals_payload()
        payload = _chart_payload()
        payload["chart"]["result"][0]["meta"] = {
            "symbol": "005930.KS",
            "currency": "KRW",
        }
        return payload

    monkeypatch.setattr("trzip.company_adapters._json_request", fake_json_request)

    result = yahoo_finance_stock(
        "005930", "KOSPI", as_of=datetime(2026, 8, 15, tzinfo=UTC)
    )

    assert result["status"] == "observed"
    assert result["yahoo_symbol"] == "005930.KS"
    assert result["summary"]["currency"] == "KRW"
    assert result["summary"]["market_cap_krw"] == 250_000_000_000
    assert result["summary"]["close_krw"] == 134.0
    assert result["fx_reference"]["provider"] == "identity"
    assert result["fx_reference"]["rate"] == 1.0
    assert len(calls) == 2
