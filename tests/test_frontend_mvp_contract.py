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
        "legacyPreviewTrends",
        "리센느",
        "두바이초콜릿",
        "두바이 초콜릿",
        "A식품",
        "H초콜릿",
        "P피스타치오무역",
        "K카다이프제분",
        "보강 중",
        "연결 중",
        "데이터 확인 중",
        "로딩 중",
    )
    for text in forbidden:
        assert text not in INDEX
        assert text not in DATA
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
    assert "return this.logoCache[name] || '';" in INDEX
    assert "const logo = company.logo_url ||" not in INDEX


def test_known_company_logos_prefer_verified_official_assets() -> None:
    official_assets = {
        "nikon.com": "https://www.nikon.com/favicon.ico",
        "teledyne.com": "https://cdn.teledyne.com/assets/common/images/favicon.ico",
        "hamamatsu.com": "https://www.hamamatsu.com/etc.clientlibs/hpk-global-web/clientlibs/clientlib-site-resources/resources/favicon.ico",
        "harim.com": "https://harim.com/main/img/ci.png",
        "harim.co.kr": "https://harim.com/main/img/ci.png",
        "company.emart.com": "https://stimg.emart.com/company/ko/images/common/sub_logo_company.png",
        "emartcompany.com": "https://stimg.emart.com/company/ko/images/common/sub_logo_company.png",
        "gsretail.com": "https://hpimg.gsretail.com/_ui/desktop/common/images/gsretail/corporation/logo_gs_en.png",
        "company.lottetour.com": "https://company.lottetour.com/images/common/header_logo.png",
        "lottetour.com": "https://company.lottetour.com/images/common/header_logo.png",
        "manutd.com": "https://contentfulproxy.stadion.io/unzgbvss5tuy/5GFoxbOTd249o0VhuZNczI/cde0cb3a7b895c6a99f2796433232819/TONAL_CREST_Black%C3%83___3x-png.png?fm=webp&fit=pad&f=center&w=184&h=184",
        "nongshim.com": "https://www.nongshim.com/resources2/images/common/pop-logo.jpg",
        "lottewellfood.com": "https://www.lottewellfood.com/favicon.ico",
    }
    for domain, url in official_assets.items():
        assert f"'{domain}': '{url}'" in INDEX
    assert "return this.officialLogoAssets[domain]" in INDEX
    assert "|| (company && company.logo_url)" in INDEX
    assert "|| (domain ? `https://www.google.com/s2/favicons" in INDEX
    assert "if (this.companyDomains[name] === logoUrl) return;" in INDEX
    assert "this.companyDomains[name] === logoUrl" in INDEX
    assert '<link rel="icon" href="data:,">' in INDEX


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
    assert 'data-sheet-price-line="1"' in INDEX
    assert 'points="{{ sheetPricePoints }}"' not in INDEX
    assert "patchCompanySheetChart()" in INDEX


def test_long_home_names_use_two_line_clamp_and_short_name() -> None:
    assert "shortDisplayName: item.short_display_name" in DATA
    assert "trend.shortName || trend.name" in INDEX or "t.shortName || t.name" in INDEX
    assert "-webkit-line-clamp:2" in INDEX
    assert "overflow-wrap:anywhere" in INDEX
    assert 'title="{{ sheetName }}"' in INDEX
    assert 'data-vd-big="1" title="트렌드"' in INDEX
    assert "el.title = top.name" in INDEX
    assert "label.length >= 16 ? '24px'" in INDEX
    assert 'title="{{ trendName }}"' in INDEX
    assert "nameStyle: 'flex:1; min-width:0;" in INDEX


def test_portfolio_surfaces_hydrate_from_presentation_feed_before_display() -> None:
    assert 'data-home-portfolios="1" style="visibility:hidden;' in INDEX
    assert 'data-portfolio-feed="1" style="visibility:hidden;' in INDEX
    assert "clearLegacyPortfolioSurfaces();" in INDEX
    assert "renderPresentationPortfolios()" in INDEX
    assert "buildPresentationPortfolios()" in INDEX
    assert "document.getElementById('dc-root') || document" in INDEX
    assert "home.setAttribute('data-hydration', 'ready')" in INDEX
    assert "feed.setAttribute('data-hydration', 'ready')" in INDEX
    assert "data-portfolio-id" in INDEX
    assert "this.portfolioById" in INDEX
    assert "homeMeta" not in INDEX


def test_maker_and_saved_portfolios_use_current_trends_and_companies() -> None:
    assert "hydrateMaker(selectedTrendId)" in INDEX
    assert 'data-trend-id="' in INDEX
    assert "trendsById.has(portfolio.trendTopic)" in INDEX
    assert "currentByName.get(this.companyName(company))" in INDEX
    assert 'data-my-stat="saved"' in INDEX
    assert 'data-my-stat="return"' in INDEX
    assert 'data-my-stat="likes"' in INDEX


def test_live_data_loader_has_timeout_and_retry_guards() -> None:
    assert "FETCH_TIMEOUT_MS = 6500" in DATA
    assert "FETCH_ATTEMPTS = 3" in DATA
    assert "async function fetchWithRetry" in DATA
    assert "new AbortController()" in DATA
    assert "fetchManifestRankings(nonce)" in DATA
    assert '<script src="./trendzip-data.js?v=' in INDEX
    assert '<script src="./support.js?v=' in INDEX
    assert "window.TRZIP_DATA_API" in INDEX
    assert "globalThis.TRZIP_DATA_API = Object.freeze" in DATA
    assert "TRZIP_DATA_API_PROMISE" not in INDEX
    assert "manifest?.bundle?.presentation || manifest?.bundle?.rankings" in DATA
    assert "if (this.publishedView)" in INDEX
    assert "window.__singleScreen(activeScreen)" in INDEX
