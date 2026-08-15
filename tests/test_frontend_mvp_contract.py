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
        "A식품",
        "H초콜릿",
        "P피스타치오무역",
        "K카다이프제분",
        "보강 중",
        "연결 중",
        "데이터 확인 중",
        "로딩 중",
        "실제 측정 이력이 아니며",
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
    assert "Math.max(img.naturalWidth, img.naturalHeight) >= policy.minimum" in INDEX
    assert "company.logo_render_mode === 'initials'" in INDEX
    assert "policy.mode === 'initials'" in INDEX
    assert "? 64" in INDEX
    assert ": Math.max(128" in INDEX
    assert "initialsOnlyLogoDomains = new Set" in INDEX
    assert "initialsOnlyLogoDomains = new Set([])" in INDEX
    assert "return this.logoCache[name] || '';" in INDEX
    assert "const logo = company.logo_url ||" not in INDEX
    assert 'data-my-stash-companies="1"' in INDEX
    assert "this.activePortfolio.companies.slice(0, 5)" in INDEX
    assert "companies.map(companyChip).join('')" in INDEX


def test_known_company_logos_prefer_verified_official_assets() -> None:
    official_assets = {
        "nikon.com": "https://www.nikon.com/etc.clientlibs/nikoncore/clientlibs/clientlib-site/resources/img/logo.svg",
        "teledyne.com": "https://cdn.teledyne.com/assets/prod/images/footerlogo.png",
        "hamamatsu.com": "https://www.hamamatsu.com/content/dam/hamamatsu-photonics/system/images/logo.svg",
        "harim.com": "https://harim.com/main/img/ci.png",
        "harim.co.kr": "https://harim.com/main/img/ci.png",
        "company.emart.com": "https://stimg.emart.com/company/ko/images/common/logo_emart_fresh.png",
        "emartcompany.com": "https://stimg.emart.com/company/ko/images/common/logo_emart_fresh.png",
        "company.lottetour.com": "https://company.lottetour.com/images/common/header_logo.png",
        "lottetour.com": "https://company.lottetour.com/images/common/header_logo.png",
        "manutd.com": "https://contentfulproxy.stadion.io/unzgbvss5tuy/5GFoxbOTd249o0VhuZNczI/cde0cb3a7b895c6a99f2796433232819/TONAL_CREST_Black%C3%83___3x-png.png?fm=webp&fit=pad&f=center&w=184&h=184",
        "nongshim.com": "https://eng.nongshim.com/resources/nongshimCss/images/ci_01.png",
        "lottewellfood.com": "https://www.lottewellfood.com/images/common/m/h1_logo_new.png",
        "sony.com": "https://www.sony.net/assets_revamp2025/images/logo.svg",
        "nvidia.com": "https://www.nvidia.com/content/dam/en-zz/Solutions/about-nvidia/nvidia-brochure/images/nvidia-logo-black.svg",
        "xpeng.com": "https://a-cdn.xpeng.com/mall/public/favicon.svg",
        "rainbow-robotics.com": "https://rainbow-robotics.com/wp-content/uploads/2026/02/logo-dark.svg",
        "ht.co.kr": "https://www.ht.co.kr/img/logo/logo_p.png",
        "wonik.com": "https://wonik.com/assets/images/favicon/apple-icon-144x144.png",
        "mazetx.com": "https://mazetx.com/wp-content/uploads/2019/10/cropped-apple-touch-icon-192x192.png",
        "gene.com": "https://www.gene.com/assets/frontend/img/favicon-prefers-light-mode.svg",
        "doosan.com": "https://www.doosan.com/images/common/favicon-152.png",
        "bi-nex.com": "https://bi-nex.com/logo192.png",
        "cj.co.kr": "https://www.cj.co.kr/resources/img/icon.png",
        "dhflour.co.kr": "https://dhflour.co.kr/image/thumbnail?code=fl6a473a28ed77a&width=144&height=144",
        "pulmuone.co.kr": "https://www.pulmuone.co.kr/pulmuone/images/sub/img_pul15.gif",
        "dxc.com": "https://dxc.com/content/dam/dxc/projects/dxc-com/global/logos/dxc/dxc-logo-png-4x.png",
        "geniussports.com": "https://cms.geniussports.com/wp-content/uploads/2024/07/4299-jCuDsESbQCzIJp7rJRm4j2W9yOu6uHA_vzxMe5hxACU.png",
        "global.canon": "https://global.canon/01cmn/img/common/logo.svg",
        "hds.co.jp": "https://www.hds.co.jp/Portals/0/files/common/images/logo_blue.png",
        "nabtesco.com": "https://www.nabtesco.com/assets/img/common/logo.svg",
        "ottogi.co.kr": "https://www.otoki.com/images/common/logo.svg",
        "shillahotels.com": "https://www.shillahotels.com/static/pc/images/svg/ci-home.svg",
        "shinsegaefood.com": "https://www.shinsegaefood.com/images/favicon/shinsegae_ci16.ico",
        "sportradar.com": "https://sportradar.com/wp-content/uploads/2023/02/Sportradar-Brand-Line_Color_Black.svg",
        "thewaltdisneycompany.com": "https://thewaltdisneycompany.com/app/uploads/2026/01/organization-logo.png",
        "ubtrobot.com": "https://owebsite-cdn.ubtrobot.com/en/uploadfiles/logo.svg",
    }
    for domain, url in official_assets.items():
        assert f"'{domain}': '{url}'" in INDEX
    assert "curatedLogoAssets = Object.freeze" in INDEX
    assert "const verifiedOverride = this.officialLogoAssets[domain] || this.curatedLogoAssets[domain]" in INDEX
    assert "if (verifiedOverride) return verifiedOverride;" in INDEX
    assert "simple-icons@latest" not in INDEX
    assert "simple-icons@13.21.0" in INDEX
    assert "simple-icons@16.24.1" in INDEX
    assert "cdn.worldvectorlogo.com/logos/cgv-cinemas.svg" in INDEX
    assert "'adobe.com': 'https://main--cc--adobecom.aem.live/cc-shared/assets/img/product-icons/svg/adobe-corp-logo-2024.svg'" in INDEX
    for domain in (
        "amctheatres.com", "apple.com", "bravesholdings.com", "cinemark.com", "daesang.com",
        "dolby.com", "fanuc.eu", "foxcorporation.com", "fujifilm.com", "hanwha.com", "hoya.com",
        "hyundai.com", "kakaocorp.com", "kodak.com", "nike.com", "ricoh.com", "samsung.com", "tesla.com",
    ):
        assert f"'{domain}': 'https://" in INDEX
    assert "return (company && company.logo_url)" in INDEX
    assert "|| (domain ? `https://www.google.com/s2/favicons" in INDEX
    assert "if (this.companyDomains[name] === logoUrl) return;" in INDEX
    assert "this.companyDomains[name] === logoUrl" in INDEX
    assert '<link rel="icon" href="data:,">' in INDEX


def test_interest_chart_is_one_combined_keyword_aware_curve() -> None:
    assert "관심 흐름" in INDEX
    assert "언급량 추이 · 관심지수" not in INDEX
    assert "buildInterestCurve(trend, rangeIndex = 0)" in INDEX
    assert "const count = [7, 11, 13][rangeIndex]" in INDEX
    assert "const rangeKey = ['1w', '1m', '3m'][rangeIndex]" in INDEX
    assert "publishedWindow.combined" in INDEX
    assert "pattern: 'published_series'" in INDEX
    assert "const keywords = Array.isArray(trend && trend.tags)" in INDEX
    assert "const signalText = [name, category, ...keywords].join(' ')" in INDEX
    assert "const eventRamp = /개기일식|유성우|말복|불꽃축제|메츠|맨유|데포르티보|오디세이|스포츠|영화|행사/.test(signalText)" in INDEX
    assert "const lateBreakout = /휴머노이드|홈플러스|재개장|로봇|출시|신제품/.test(signalText)" in INDEX
    assert "else if (eventRamp && movement.status !== 'unchanged') pattern = 'event_ramp'" in INDEX
    assert "else if (lateBreakout && movement.status !== 'unchanged') pattern = 'emerging'" in INDEX
    assert "const periodProfile = [" in INDEX
    assert "eventCenter: 0.78" in INDEX
    assert "pattern = 'cooling'" in INDEX
    assert "pattern = 'sustained'" in INDEX
    assert "pattern = 'event_ramp'" in INDEX
    assert "pattern = 'rebounding'" in INDEX
    assert "const middleDip =" in INDEX
    assert "const lateRebound =" in INDEX
    assert "values[index - 1] + 0.65" not in INDEX
    assert 'data-interest-line="1"' in INDEX
    assert 'data-interest-area="1"' in INDEX
    assert 'aria-labelledby="interest-chart-title interest-chart-disclosure"' in INDEX
    assert "관심 흐름은 기간별 비교를 위한 정규화 지수입니다." in INDEX
    assert "patchInterestChart()" in INDEX
    assert "sourceSignals" in INDEX
    assert "sourceLabels.length ? sourceLabels : ['X']" not in INDEX
    assert "출처 미확인" in INDEX
    assert "displayOnly: true" in INDEX
    assert "rankingEffect: 'none'" in INDEX
    chart_surface = INDEX[INDEX.index("관심 흐름"): INDEX.index("함께 언급된 키워드")]
    assert "chartPanels" not in chart_surface
    assert "전체 채널" not in chart_surface
    assert "채널 추가하기" not in chart_surface
    assert "buildChartPanels(" not in INDEX
    assert "chartRevealWire()" not in INDEX


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
    assert "관계 등급" not in INDEX
    assert "근거 상태" not in INDEX
    assert "기업 연결 근거 보기" not in INDEX
    assert "트렌드와 연결된 이유" in INDEX
    assert "{{ sheetReason }}" in INDEX
    assert "관심기업 등록" in INDEX
    assert "키움 종목홈으로 가기" in INDEX
    assert "trzip_company_watchlist_v1" in INDEX
    assert "https://www.kiwoom.com/h/domestic/stock/VStockMainView" in INDEX


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


def test_popular_portfolios_keep_the_approved_community_seed_examples() -> None:
    for title in (
        "리센느 매매법",
        "두바이초콜릿 이름값 3종 담았다",
        "초콜릿 원재료 쪽으로 파봤습니다",
        "이름 안 겹쳐도 수혜주는 따로 있다",
    ):
        assert title in INDEX
    for company in ("원익", "리브스메드", "두산", "바이넥스", "한국콜마", "오리온", "CJ제일제당", "대한제분"):
        assert company in INDEX
    assert "dataMode: 'seed_portfolio'" in INDEX
    assert "수익률순" not in INDEX
    assert "내 포트 수익률" not in INDEX
    assert "등락순" in INDEX
    assert "구성 평균 등락" in INDEX


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


def test_status_bars_show_live_kst_instead_of_fixed_mock_time() -> None:
    assert INDEX.count('<span data-status-time="kst">') == 8
    assert ">9:41<" not in INDEX
    assert "syncStatusClock(now = new Date())" in INDEX
    assert "timeZone: 'Asia/Seoul'" in INDEX
    assert "hourCycle: 'h23'" in INDEX
    assert "60000 - (Date.now() % 60000)" in INDEX
    assert "setInterval(tick, 60000)" in INDEX


def test_list_view_uses_previous_publication_rank_movement_not_weekly_percent() -> None:
    assert "rankMovement: movement" in DATA
    assert "previous_published_presentation_feed" in DATA
    assert "rankMovementLabel" in INDEX
    assert "movement.status === 'up'" in INDEX
    assert "movement.status === 'down'" in INDEX
    assert "이전 발행 대비" in INDEX
    list_renderer = INDEX[INDEX.index("const list = document.querySelector('[data-list-view2]');"):]
    list_renderer = list_renderer[: list_renderer.index("  dialGo(label)")]
    assert "trend.lift" not in list_renderer
    assert "최근 1주" not in list_renderer


def test_production_has_one_phone_screen_without_public_debug_navigation() -> None:
    assert '<html lang="ko">' in INDEX
    assert "#proto-nav" not in INDEX
    assert "debugNavEnabled" not in INDEX
    assert "new URLSearchParams(window.location.search).get('debug')" not in INDEX
    assert "setInterval(build, 400)" not in INDEX
    assert "window.__singleScreen" in INDEX


def test_reviewed_archive_is_loaded_separately_from_live_ranking() -> None:
    for token in (
        "ARCHIVE_URL = './trend-archive.json'",
        "validatedArchive(payload)",
        "async function loadArchive()",
        "data_mode !== 'reconstructed_reference'",
        "ranking_eligible !== false",
        "ranking_effect !== 'none'",
    ):
        assert token in DATA
    assert 'data-archive-open="1"' in INDEX
    assert "openArchive = async () =>" in INDEX
    assert "검수된 과거 트렌드" in INDEX
    assert "실시간 순위에는 반영하지 않습니다." in INDEX
    assert "기업 연결 맥락 보기" in INDEX
    assert "data-archive-case" in INDEX
    assert "순위" not in INDEX[INDEX.index("openArchive = async () =>"):INDEX.index("  setOwnerMode(on)")].replace("실시간 순위에는 반영하지 않습니다.", "")


def test_selection_disclosure_and_portfolio_safety_rules_are_visible_and_enforced() -> None:
    assert "openSelectionGuide" in INDEX
    assert "트렌드 선정 기준" in INDEX
    assert "정치·범죄·재난·사생활·혐오" in INDEX
    assert "관측 강도·교차 확산·지속성" in INDEX
    assert "validatePortfolioContent(input = {})" in DATA
    assert "UNSAFE_PORTFOLIO_TEXT" in DATA
    assert "정치·범죄·혐오·수익 보장 표현은 공개할 수 없습니다." in DATA
    assert "validatePortfolioContent(input);" in DATA
    assert "portfolio_create_blocked" in INDEX
    assert "deletePortfolio(id)" in DATA


def test_trend_selector_uses_consistent_vector_images_instead_of_unicode_emoji() -> None:
    assert "const TWEMOJI_SVG_BASE = 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/svg/'" in INDEX
    assert '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin="anonymous">' in INDEX
    assert 'src="{{ opt.optIconUrl }}"' in INDEX
    assert 'alt="{{ opt.optIconAlt }}"' in INDEX
    assert 'object-fit:contain' in INDEX
    assert 'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';"' in INDEX
    assert '{{ opt.optIconFallback }}' in INDEX
    assert '{{ opt.optEmoji }}' not in INDEX
    assert 'optEmoji: t.emoji' not in INDEX

    # 유성우는 일식·달 아이콘을 재사용하지 않고 별똥별 벡터를 쓴다.
    assert "[/페르세우스|유성우|별똥별/, '1f320', '유']" in INDEX
    assert "[/개기일식|일식/, '1f311', '일']" in INDEX

    # 승인 Top10의 모든 의미 유형이 하나의 핀 고정 벡터 라이브러리로 매핑된다.
    for code in ('1f320', '1f311', '1f372', '1f386', '26be', '26bd', '1f3ac', '1f916', '1f3ec'):
        assert f"'{code}'" in INDEX
