from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
DATA = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")


def test_frontend_has_no_demo_or_export_ui_copy() -> None:
    forbidden = (
        "시연용",
        "실제 데이터가 아닙니다",
        "축적 중",
        "밍트폴리오",
        "JSON 내보내기",
        "CSV 내보내기",
    )
    for text in forbidden:
        assert text not in INDEX
    assert "exportPortfoliosJson" not in DATA
    assert "exportPortfoliosCsv" not in DATA
    assert "trzip-export-v1" not in DATA


def test_company_logos_are_used_across_company_and_portfolio_surfaces() -> None:
    assert "company.logo_url" in INDEX
    assert "data-mk-stock" in INDEX
    assert "data-pd=\"box\"" in INDEX
    assert "portfolio.companies.map" in INDEX
    assert "center/contain no-repeat" in INDEX
    assert "center/cover no-repeat" not in INDEX
    assert "img.naturalWidth >= 16" in INDEX


def test_chart_uses_selected_period_and_all_x_google_series() -> None:
    assert "visualizationSeries: item.visualization_series || {}" in DATA
    assert "buildChartPanels(t, rangeIndex = 0)" in INDEX
    assert "['1w', '1m', '3m'][rangeIndex]" in INDEX
    assert "this.buildChartPanels(curTrend, this.state.range)" in INDEX
    assert "전체 채널" in INDEX
    assert "Google 검색" in INDEX
    assert "domain=x.com" in INDEX


def test_company_sheet_contains_price_chart_and_valuation_metrics() -> None:
    for token in (
        "30일 주가 추이",
        "sheetPricePoints",
        "sheetMarketCap",
        "sheetPer",
        "sheetPbr",
        "sheetRoe",
        "market_snapshot",
    ):
        assert token in INDEX
    assert "snapshot.last_price_label || formatPrice(lastPrice)" in INDEX


def test_long_home_names_use_two_line_clamp_and_short_name() -> None:
    assert "shortDisplayName: item.short_display_name" in DATA
    assert "trend.shortName || trend.name" in INDEX or "t.shortName || t.name" in INDEX
    assert "-webkit-line-clamp:2" in INDEX


def test_live_data_loader_has_timeout_and_retry_guards() -> None:
    assert "FETCH_TIMEOUT_MS = 6500" in DATA
    assert "FETCH_ATTEMPTS = 3" in DATA
    assert "async function fetchWithRetry" in DATA
    assert "new AbortController()" in DATA
    assert "fetchManifestRankings(nonce)" in DATA
    assert '<script src="./trendzip-data.js"></script>' in INDEX
    assert "window.TRZIP_DATA_API" in INDEX
    assert "globalThis.TRZIP_DATA_API = Object.freeze" in DATA
    assert "TRZIP_DATA_API_PROMISE" not in INDEX
