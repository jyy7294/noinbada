from trzip.company_adapters import OHLCV_COLUMNS, _market_reaction


def test_pykrx_columns_have_stable_frontend_names():
    assert OHLCV_COLUMNS["종가"] == "close"
    assert OHLCV_COLUMNS["거래량"] == "volume"


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
