from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
DATA = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")
STOCKS = (ROOT / "frontend" / "mock-stock-universe.js").read_text(encoding="utf-8")


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
        "저장본",
        "시연용",
        "표시용",
        "실측 아님",
        "발행본",
        "축적중",
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
    assert "img.naturalWidth >= policy.minimum && img.naturalHeight >= policy.minimum" in INDEX
    assert "this.seedRasterSharpEnough(img.naturalWidth, img.naturalHeight, policy)" in INDEX
    assert "seedRenderBox: seedAssetSelected ? 34 : null" in INDEX
    assert "seedMinimumPixelDensity: seedAssetSelected ? 2 : null" in INDEX
    assert "Math.max(img.naturalWidth, img.naturalHeight) >= policy.minimum" not in INDEX
    assert "company.logo_render_mode !== 'image'" in INDEX
    assert "policy.mode === 'initials'" in INDEX
    assert "minimum: 64" in INDEX
    assert "initialsOnlyLogoDomains = new Set" in INDEX
    assert "initialsOnlyLogoDomains = new Set([])" in INDEX
    assert "if (!candidate) return '';" in INDEX
    assert "this.companyDomains[name] === candidate ? (this.logoCache[name] || '') : ''" in INDEX
    assert "const logo = company.logo_url ||" not in INDEX
    assert 'data-my-stash-companies="1"' in INDEX
    assert "this.activePortfolio.companies.slice(0, 5)" in INDEX
    assert "companies.map(companyChip).join('')" in INDEX


def test_known_company_logo_assets_are_confined_to_seed_meme_portfolios() -> None:
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
        "ht.co.kr": "https://www.ht.co.kr/img/icon/favicon.ico",
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
    assert "company.logo_asset_scope === 'seed_meme_portfolio'" in INDEX
    assert "logo_asset_scope: 'seed_meme_portfolio'" in INDEX
    assert "if (this.isSeedMemeLogo(company))" in INDEX
    assert "return this.officialLogoAssets[domain] || this.curatedLogoAssets[domain] || '';" in INDEX
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
    assert "return this.isVerifiedPublishedLogo(company) ? String(company.logo_url || '') : '';" in INDEX
    assert "https://www.google.com/s2/favicons" not in INDEX
    assert "if (this.companyDomains[name] === logoUrl) return;" in INDEX
    assert "this.companyDomains[name] === logoUrl" in INDEX
    assert '<link rel="icon" href="data:,">' in INDEX


def test_live_company_logo_requires_v4_verified_provenance_or_initials() -> None:
    required_checks = (
        "company.logo_render_mode !== 'image'",
        "verification === 'verified_safe_svg' && format === 'svg'",
        "verification === 'verified_raster_min_64px'",
        "width >= 64 && height >= 64",
        "company.logo_asset_source === 'official_page_asset'",
        "company.logo_runtime_probe_required === false",
        "provenance.asset_url === url",
        "provenance.source_page_url === sourcePageUrl",
        "provenance.sha256 === sha256",
        "provenance.verification === verification",
    )
    for check in required_checks:
        assert check in INDEX
    assert "return this.isVerifiedPublishedLogo(company) ? String(company.logo_url || '') : '';" in INDEX
    assert "img.naturalWidth >= policy.minimum && img.naturalHeight >= policy.minimum" in INDEX


def test_maker_stock_search_uses_only_verified_official_logo_scope() -> None:
    assert "logo_asset_scope: 'maker_stock_search'" in STOCKS
    assert "logo_runtime_probe_required: false" in STOCKS
    assert "logo_render_mode: 'runtime_probe'" not in STOCKS
    assert "isMakerStockLogo(company)" in INDEX
    assert "company.logo_asset_scope !== 'maker_stock_search'" in INDEX

    script = r"""
      const fs = require('fs');
      const vm = require('vm');
      const code = fs.readFileSync('./frontend/mock-stock-universe.js', 'utf8');
      const sandbox = {};
      vm.createContext(sandbox);
      vm.runInContext(code, sandbox);
      const rows = sandbox.TRZIP_STOCK_UNIVERSE;
      if (!Array.isArray(rows) || rows.length < 50) throw new Error('stock universe missing');
      const visibleDomesticIds = new Set([
        ...rows.filter((row) => row.popular_rank).sort((a, b) => a.popular_rank - b.popular_rank).slice(0, 12).map((row) => row.id),
        ...rows.filter((row) => row.recent_rank).sort((a, b) => a.recent_rank - b.recent_rank).slice(0, 6).map((row) => row.id),
      ]);
      const foreign = rows.filter((row) => !/^(KRX|KOSPI|KOSDAQ)$/i.test(row.exchange)).slice(0, 12);
      const visible = [...rows.filter((row) => visibleDomesticIds.has(row.id)), ...foreign];
      if (visible.length !== 27) throw new Error('unexpected visible stock set: ' + visible.length);
      visible.forEach((row) => {
        if (row.id === 'us-MSFT') {
          if (row.logo_render_mode !== 'initials' || row.logo_url !== '') {
            throw new Error('Microsoft must remain initials-only');
          }
          return;
        }
        const p = row.logo_provenance || {};
        if (row.logo_asset_scope !== 'maker_stock_search') throw new Error(row.id + ': scope');
        if (row.logo_render_mode !== 'image') throw new Error(row.id + ': image mode');
        if (row.logo_runtime_probe_required !== false) throw new Error(row.id + ': runtime probe');
        if (!/^https:\/\//.test(row.logo_url) || !/^https:\/\//.test(row.logo_source_page_url)) throw new Error(row.id + ': url');
        if (!/^[0-9a-f]{64}$/.test(row.logo_asset_sha256)) throw new Error(row.id + ': sha');
        if (row.logo_asset_format === 'svg') {
          if (row.logo_asset_verification !== 'verified_safe_svg') throw new Error(row.id + ': svg verification');
        } else if (!(row.logo_asset_width >= 64 && row.logo_asset_height >= 64
          && row.logo_asset_verification === 'verified_raster_min_64px')) {
          throw new Error(row.id + ': raster dimensions');
        }
        if (p.asset_url !== row.logo_url || p.source_page_url !== row.logo_source_page_url
          || p.mime !== row.logo_asset_mime || p.width !== row.logo_asset_width
          || p.height !== row.logo_asset_height || p.sha256 !== row.logo_asset_sha256
          || p.verification !== row.logo_asset_verification) throw new Error(row.id + ': provenance');
      });
      const unpinned = rows.find((row) => row.id === 'kr-086790');
      if (!unpinned || unpinned.logo_render_mode !== 'initials' || unpinned.logo_url !== '') {
        throw new Error('unverified fallback is not initials');
      }
      const kakao = rows.find((row) => row.id === 'kr-035720');
      if (!kakao || kakao.logo_url !== 'https://t1.kakaocdn.net/kakaocorp/corp_thumbnail/Kakao.png'
        || kakao.logo_asset_format !== 'png' || kakao.logo_asset_width !== 800
        || kakao.logo_asset_height !== 800
        || kakao.logo_asset_sha256 !== '63ad018488cf671e4e74d26ec24c0ef7990ac23605bdbbd953ac33df4b7e48ce') {
        throw new Error('Kakao official 800px asset missing');
      }
      const html = fs.readFileSync('./frontend/index.html', 'utf8');
      const match = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/);
      const Component = new Function('DCLogic', match[1] + ';return Component;')(
        class { forceUpdate() {} }
      );
      const component = new Component();
      const maker = visible[0];
      if (component.isVerifiedPublishedLogo(maker)) throw new Error('maker scope leaked into live logo contract');
      if (!component.isMakerStockLogo(maker) || component.logoCandidate(maker) !== maker.logo_url) {
        throw new Error('verified maker logo rejected');
      }
      if (component.logoPolicy(maker, maker.logo_url).mode !== 'maker_stock_search') {
        throw new Error('maker logo priority scope was not preserved');
      }
      const tampered = {...maker, logo_asset_sha256: '0'.repeat(64)};
      if (component.logoCandidate(tampered) !== '') throw new Error('tampered maker logo accepted');

      // A newly opened market tab must move its visible maker logos ahead of
      // the previous tab's remaining preload queue without changing live-v4 policy.
      global.Image = class { set src(_value) {} };
      const preloader = new Component();
      const domesticBatch = visible.filter((row) => /^(KRX|KOSPI|KOSDAQ)$/i.test(row.exchange)).slice(0, 6);
      domesticBatch.forEach((row) => preloader.registerLogo(row.name_en, row.logo_url, row));
      foreign.slice(0, 6).forEach((row) => preloader.registerLogo(row.name_en, row.logo_url, row, true));
      const queuedNames = (preloader.__logoQueue || []).map(([name]) => name);
      const foreignNames = foreign.slice(0, 6)
        .filter((row) => row.logo_render_mode === 'image')
        .map((row) => row.name_en);
      if (JSON.stringify(queuedNames.slice(0, foreignNames.length)) !== JSON.stringify(foreignNames)) {
        throw new Error('visible foreign logos were left behind the domestic preload queue');
      }
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_live_logo_candidate_runtime_honors_initials_and_seed_scope() -> None:
    script = r"""
      const fs = require('fs');
      const html = fs.readFileSync('./frontend/index.html', 'utf8');
      const match = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/);
      const Component = new Function('DCLogic', match[1] + ';return Component;')(
        class { forceUpdate() {} }
      );
      const component = new Component();
      const sha = 'a'.repeat(64);
      const verified = {
        company: 'Nikon', official_domain: 'nikon.com',
        logo_url: 'https://www.nikon.com/logo.svg', logo_render_mode: 'image',
        logo_asset_source: 'official_page_asset', logo_asset_verification: 'verified_safe_svg',
        logo_asset_format: 'svg', logo_asset_mime: 'image/svg+xml',
        logo_asset_width: 400, logo_asset_height: 400, logo_asset_sha256: sha,
        logo_source_page_url: 'https://www.nikon.com/', logo_runtime_probe_required: false,
        logo_provenance: {
          asset_url: 'https://www.nikon.com/logo.svg', source_page_url: 'https://www.nikon.com/',
          mime: 'image/svg+xml', width: 400, height: 400, sha256: sha,
          verification: 'verified_safe_svg'
        }
      };
      if (component.logoCandidate({...verified, logo_render_mode: 'initials'}) !== '') {
        throw new Error('initials mode bypassed');
      }
      if (component.logoCandidate(verified) !== verified.logo_url) {
        throw new Error('verified SVG rejected');
      }
      const raster = {
        ...verified, logo_url: 'https://www.nikon.com/logo.png',
        logo_asset_verification: 'verified_raster_min_64px', logo_asset_format: 'png',
        logo_asset_mime: 'image/png', logo_asset_width: 63, logo_asset_height: 200
      };
      raster.logo_provenance = {
        asset_url: raster.logo_url, source_page_url: raster.logo_source_page_url,
        mime: raster.logo_asset_mime, width: 63, height: 200, sha256: sha,
        verification: raster.logo_asset_verification
      };
      if (component.logoCandidate(raster) !== '') throw new Error('low-width raster accepted');
      const seed = {
        company: 'Seed Company', official_domain: 'wonik.com',
        logo_asset_scope: 'seed_meme_portfolio'
      };
      if (!component.logoCandidate(seed)) throw new Error('seed asset rejected');
      const seedWordmarks = [
        ['livsmed.com', 306, 60],
        ['orionworld.com', 135, 29],
        ['crown.co.kr', 240, 54],
        ['ht.co.kr', 256, 229],
      ];
      seedWordmarks.forEach(([domain, width, height]) => {
        const company = {company: domain, official_domain: domain, logo_asset_scope: 'seed_meme_portfolio'};
        const logo = component.logoCandidate(company);
        const policy = component.logoPolicy(company, logo);
        if (policy.mode !== 'seed_meme_portfolio' || policy.seedRenderBox !== 34
          || policy.seedMinimumPixelDensity !== 2
          || !component.seedRasterSharpEnough(width, height, policy)) {
          throw new Error(domain + ': contain-density gate rejected a sharp official wordmark');
        }
      });
      const seedPolicy = component.logoPolicy(seed, component.logoCandidate(seed));
      if (component.seedRasterSharpEnough(60, 12, seedPolicy)) {
        throw new Error('undersized seed wordmark was accepted');
      }
      const livePolicy = component.logoPolicy(verified, verified.logo_url);
      if (livePolicy.mode !== 'image' || livePolicy.minimum !== 64
        || livePolicy.seedRenderBox !== null || livePolicy.seedMinimumPixelDensity !== null) {
        throw new Error('seed density policy leaked into live-v4');
      }
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_interest_chart_uses_only_observed_24h_series_and_preserves_gaps() -> None:
    assert "관심 흐름" in INDEX
    assert "언급량 추이 · 관심지수" in INDEX
    assert "buildInterestCurve(trend, rangeIndex = 0)" in INDEX
    assert "const rangeKey = ['24h', '1m', '3m'][rangeIndex]" in INDEX
    assert "point.provenance === 'observed'" in INDEX
    assert "['x', 'google_trends'].includes(point.source)" in INDEX
    assert "latestObservedMs - atMs > 24 * 60 * 60 * 1000" in INDEX
    assert "const groupedObserved = new Map()" in INDEX
    assert "point.timestamp || point.at" in INDEX
    assert "point && point.combined" in INDEX
    assert "publishedWindow.combined" in INDEX
    assert "pattern: 'published_series'" in INDEX
    assert "const usable = rawValues.filter(Number.isFinite)" in INDEX
    assert "if (usable.length < 2)" in INDEX
    assert "available: false" in INDEX
    assert "const MAX_CONTIGUOUS_GAP_MS = 90 * 60 * 1000" in INDEX
    assert "currentTimestamp - previousTimestamp > MAX_CONTIGUOUS_GAP_MS" in INDEX
    assert "segments.filter((segment) => segment.length >= 2).map" in INDEX
    assert "segments.filter((segment) => segment.length === 1)" in INDEX
    assert 'data-interest-single-points="1"' in INDEX
    assert "else if (activeSegment.length)" in INDEX
    assert "linePath" in INDEX
    assert "data-interest-empty=\"1\"" in INDEX
    assert "rangeAvailability" in INDEX
    assert "aria-disabled=\"{{ rangeDisabled0 }}\"" in INDEX
    for synthetic_token in ("event_ramp", "lateBreakout", "middleDip", "lateRebound", "periodProfile"):
        assert synthetic_token not in INDEX
    assert 'data-interest-line="1"' in INDEX
    assert 'data-interest-area="1"' in INDEX
    assert 'aria-labelledby="interest-chart-title interest-chart-disclosure"' in INDEX
    assert "관심 흐름은 기간별 비교를 위한 정규화 지수입니다." in INDEX
    assert "patchInterestChart()" in INDEX
    assert "sourceSignals" in INDEX
    assert "sourceLabels.length ? sourceLabels : ['X']" not in INDEX
    assert "if (!window || window.percent == null) return '—';" in INDEX
    assert "if (!Number.isFinite(value)) return '—';" in INDEX
    assert "item.attentionLift && item.attentionLift.label ? item.attentionLift.label : '—'" in INDEX
    assert "return '0.0%'" not in INDEX
    assert "출처 미확인" in INDEX
    assert "displayOnly: true" not in INDEX
    chart_surface = INDEX[INDEX.index("관심 흐름"): INDEX.index("함께 언급된 키워드")]
    assert "chartPanels" not in chart_surface
    assert "전체 채널" not in chart_surface
    assert "채널 추가하기" not in chart_surface
    assert "buildChartPanels(" not in INDEX
    assert "chartRevealWire()" not in INDEX


def test_company_sheet_renders_financial_numbers_only_with_complete_provenance() -> None:
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
    assert "verifiedMarketSnapshot(company)" in INDEX
    assert "snapshot.status !== 'observed'" in INDEX
    assert "!/^[A-Z]{3}$/.test(currency)" in INDEX
    assert "const verifiedSnapshot = this.verifiedMarketSnapshot(company)" in INDEX
    assert "const hasProvenance = Boolean(verifiedSnapshot)" in INDEX
    assert "sheetHasMarketData" in INDEX
    assert "sheetHasPriceSeries" in INDEX
    assert '<sc-if value="{{ sheetHasMarketData }}"' in INDEX
    assert '<sc-if value="{{ sheetMarketUnavailable }}"' in INDEX
    assert 'data-sheet-market-unavailable="1"' in INDEX
    assert "시장 자료를 확인하지 못했습니다" in INDEX
    assert "? points : ''" in INDEX
    assert "const seed = [...String(market" not in INDEX
    assert "Array.from({ length: 30 }" not in INDEX
    assert "['1.8조', '4.2조'" not in INDEX
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
    assert "new Intl.NumberFormat('ko-KR'" in INDEX
    assert "style: 'currency', currency" in INDEX
    assert "snapshot.market_cap_currency === 'KRW'" in INDEX
    assert "snapshot.market_cap_krw" in INDEX
    assert "snapshot.fx_rate_to_krw" in INDEX
    assert "snapshot.fx_source_url" in INDEX
    assert "snapshot.display_only !== true" in INDEX
    assert "snapshot.ranking_effect !== 'none'" in INDEX
    assert "prices.length === 30" in INDEX
    assert "providerLooksSynthetic" in INDEX
    assert "formatKrwMarketCap(marketCapKrw)" in INDEX
    assert "시가총액·원화" in INDEX
    assert "formatMarketCap(snapshot.market_cap)" not in INDEX
    assert "snapshot.market_cap_label" not in INDEX


def test_market_snapshot_guard_rejects_unverified_values_and_preserves_real_zero_roe() -> None:
    guard_methods = INDEX[
        INDEX.index("  verifiedMarketSnapshot(company) {"):
        INDEX.index("  signedPercent(value) {")
    ]
    build_sheet = INDEX[
        INDEX.index("  buildSheet(initial, name, desc, i, icon, company = {}) {"):
        INDEX.index("\n  snsRoot()", INDEX.index("  buildSheet(initial, name, desc, i, icon, company = {}) {"))
    ]
    script = f"""
      class Guard {{
        companyLogo() {{ return ''; }}
        {guard_methods}
        {build_sheet}
      }}
      const guard = new Guard();
      const observed = {{market_snapshot: {{
        status: 'observed', provider: 'yahoo_finance', as_of: '2026-08-15',
        source_url: 'https://example.com/market', price_source_url: 'https://example.com/price', currency: 'USD',
        last_price: 100, change_percent: null, price_series: Array.from({{length: 30}}, (_, i) => 90 + i),
        display_only: true, ranking_effect: 'none', per: null, pbr: null, roe: 0,
        roe_source_url: 'https://example.com/roe', roe_calculated: true,
        roe_basis: 'trailing_net_income / average_two_point_stockholders_equity * 100',
        roe_numerator: {{value: 0, as_of: '2026-08-15'}},
        roe_denominator: {{value: 100, observations: [{{value: 100}}, {{value: 100}}]}}
      }}}};
      if (!guard.verifiedMarketSnapshot(observed)) process.exit(11);
      if (guard.companyChange(observed) !== null) process.exit(12);
      if (guard.companyPrice(observed) === '–') process.exit(13);
      const sheet = guard.buildSheet('A', 'Acme', 'desc', 0, '', observed);
      if (!sheet.hasMarketData || sheet.marketUnavailable) process.exit(14);
      if (sheet.per !== '—' || sheet.pbr !== '—' || sheet.roe !== '0.0%') process.exit(15);

      for (const mutation of [
        {{status: 'unavailable'}},
        {{source_url: ''}},
        {{price_source_url: ''}},
        {{currency: ''}},
        {{display_only: false}},
        {{price_series: [90, 100]}},
      ]) {{
        const company = {{market_snapshot: {{...observed.market_snapshot, ...mutation}}}};
        if (guard.verifiedMarketSnapshot(company) !== null) process.exit(21);
        if (guard.companyChange(company) !== null || guard.companyPrice(company) !== '–') process.exit(22);
        const unavailable = guard.buildSheet('A', 'Acme', 'desc', 0, '', company);
        if (unavailable.hasMarketData || !unavailable.marketUnavailable) process.exit(23);
      }}
      console.log('market snapshot guard ok');
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "market snapshot guard ok" in result.stdout


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


def test_seed_meme_portfolios_never_present_invented_stock_prices_or_returns() -> None:
    seed_block = INDEX.split("buildPresentationPortfolios()", 1)[1].split(
        "portfolioLogoMarkup", 1
    )[0]
    assert "market_snapshot" not in seed_block
    assert "change_percent" not in seed_block
    assert "last_price" not in seed_block
    for invented_value in ("17.8", "24.4", "39840", "104500", "267500"):
        assert invented_value not in seed_block


def test_maker_and_saved_portfolios_use_current_trends_and_companies() -> None:
    assert "hydrateMaker(selectedTrendId)" in INDEX
    assert "this.hydrateMaker();\n        this.mkWire();" in INDEX
    assert "if (!page) return;\n    page.__mk = true;" in INDEX
    assert "if (!page || page.__mk) return;" not in INDEX
    assert "#dc-root > section { position: fixed !important" in INDEX
    assert "#dc-root section { position: fixed !important" not in INDEX
    assert 'data-trend-id="' in INDEX
    assert "currentByName.get(this.companyName(company))" in INDEX
    assert 'data-my-stat="saved"' in INDEX
    assert 'data-my-stat="return"' in INDEX
    assert 'data-my-stat="likes"' in INDEX


def test_live_data_loader_has_timeout_and_retry_guards() -> None:
    assert "DEFAULT_LIVE_DATA_BASE = 'https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest'" in DATA
    assert "['127.0.0.1', 'localhost'].includes(globalThis.location?.hostname)" in DATA
    assert "new URLSearchParams(globalThis.location.search).get('dataBase')" in DATA
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
    assert "이전 공개 대비" in INDEX
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
    assert "[data-screen-label] { display:none !important; }" in INDEX
    assert "[data-screen-label][data-proto-active] { display:flex !important; }" in INDEX
    assert "body > x-dc > section > div:first-child { display:none !important; }" in INDEX


def test_core_touch_targets_use_semantic_buttons() -> None:
    assert '<button type="button" aria-label="첫 번째 트렌드 선택" data-vd="0"' in INDEX
    assert '<button type="button" data-my-entry="1" aria-label="마이페이지 열기"' in INDEX
    assert '<button type="button" data-mk="open" aria-label="새 밈트폴리오 만들기"' in INDEX
    assert '<button type="button" data-pd="stashBtn"' in INDEX
    assert '<button type="button" data-pd="editBtn"' in INDEX
    assert '<button type="button" data-pd="delBtn"' in INDEX
    assert '<svg onClick=' not in INDEX
    assert '<div data-mk="open"' not in INDEX
    assert '<div data-pd="stashBtn"' not in INDEX


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


def test_selection_disclosure_distinguishes_source_rank_from_home_candidate_order() -> None:
    assert "SelectionScore = 35V + 25B + 20A + 10P + 10R" in INDEX
    for component in ("상승 속도", "교차 확산", "현재 관심", "반복 관측", "최신성"):
        assert component in INDEX
    assert "원천 관측 순위가 아니라 홈 공개 후보의 내부 정렬식" in INDEX
    assert "X·Google 원천 관측 점수는 별도 Python 산식" in INDEX
    assert "LLM 문구, 관련 키워드 수, 기업 수는 어느 점수에도 가점으로 반영하지 않습니다." in INDEX
    assert "4시간 단위" in INDEX
    assert "원천 순위와 홈 후보 내부 점수를 바꾸지 않습니다." in INDEX


def test_live_home_accepts_only_v4_validated_non_synthetic_feed_and_allows_zero_to_ten() -> None:
    assert "feed.schema_version === 'trzip-presentation-feed-v4'" in DATA
    assert "feed.selection_policy === 'validated_live_home_feed_v1'" in DATA
    assert "feed.transition?.synthetic_data_used === false" in DATA
    assert "feed.transition?.supplemental_display_data_used === false" in DATA
    assert "feed.transition?.fallback_used === false" in DATA
    assert "feed.transition?.padding_forbidden === true" in DATA
    assert "feed.transition?.canonical_ranking_affected === false" in DATA
    assert "item?.selection_origin === 'canonical_validated_home_feed'" in DATA
    assert "item?.lane === 'main'" in DATA
    assert "item?.data_mode === 'observed_live'" in DATA
    assert "item?.observed_within_24h === true" in DATA
    assert "validObservedSeries(item, observedAt)" in DATA
    assert "validSparseVisualization(item)" in DATA
    assert "keywords.length === 5" in DATA
    assert "keywordTexts.every(keywordFitsPublicLabel)" in DATA
    assert "companies.length === 10" in DATA
    assert "companyIdentities.size === 10" in DATA
    assert "roles.size >= 2" in DATA
    assert "roles.size <= 4" in DATA
    assert "ontologyPathReachesCompany(company.ontology_path" in DATA
    assert "validLiveLogo(company)" in DATA
    assert "linkedKeywords.size >= 2" in DATA
    assert "feed.status === 'empty' && items.length === 0" in DATA
    assert "feed.status === 'ready' && items.length > 0 && items.length <= 10" in DATA
    assert "function selectLiveHomeRows(payload, { fromCache = false, stale = false } = {})" in DATA
    assert "const eligible = !fromCache" in DATA
    assert "stale: status.stale" in DATA
    assert "const publicRows = liveHomeSelection.items" in DATA
    assert "payload.public_top10" not in DATA[DATA.index("function viewModel("):DATA.index("async function loadTrends(")]
    assert "feed && feed.schema_version === 'trzip-presentation-feed-v4'" in INDEX
    assert "feed.transition.synthetic_data_used === false" in INDEX
    assert "feed.transition.supplemental_display_data_used === false" in INDEX
    assert "feed.transition.fallback_used === false" in INDEX
    assert "feed.transition.padding_forbidden === true" in INDEX
    assert "feed.transition.canonical_ranking_affected === false" in INDEX
    assert "secondaryLiveHomeSelection.eligible === true" in INDEX
    assert "item.selection_origin === 'canonical_validated_home_feed'" in INDEX
    assert "item.lane === 'main'" in INDEX
    assert "item.data_mode === 'observed_live'" in INDEX
    assert "feed.status === 'empty' && feedItems.length === 0" in INDEX
    assert "feed.status === 'ready' && feedItems.length > 0 && feedItems.length <= 10" in INDEX
    assert "feed.items.length !== 10" not in INDEX
    assert "const expectedCount = liveHomeEligible ? feed.items.length : 0" in INDEX
    assert "현재 공개 기준을 충족한 흐름이 없습니다" in INDEX
    assert 'data-home-empty="1"' in INDEX
    assert "[data-vd-pill]" in INDEX[INDEX.index("const dialParts"):INDEX.index("if (top && top.emptyState)")]
    assert "if (!this.hasPublishedTrends || (this.trends[0] && this.trends[0].emptyState))" in INDEX
    assert "if (!this.hasPublishedTrends" in INDEX
    assert "const t = this.trends[i];" in INDEX
    assert "this.trends[i % this.trends.length]" not in INDEX


def test_v4_live_home_fixtures_cover_zero_to_ten_and_fail_closed_fields() -> None:
    script = r"""
      require('./frontend/trendzip-data.js');
      const api = globalThis.TRZIP_DATA_API;
      if (!api || typeof api.selectLiveHomeRows !== 'function') process.exit(2);
      const observedAt = '2026-08-15T05:00:00.000Z';
      const roles = ['manufacturing_development', 'distribution', 'retail_sales'];
      const logoPolicy = {
        version: 'avatar-sharpness-v1', avatar_size_px: 44,
        minimum_raster_dimension_px: 64, vector_assets_allowed: true,
        low_resolution_fallback: 'initials', runtime_probe_for_generic_favicons: false,
        official_page_resolver_required: true, asset_sha256_required: true,
      };
      const transition = {
        synthetic_data_used: false, supplemental_display_data_used: false,
        fallback_used: false, padding_forbidden: true,
        canonical_ranking_affected: false,
      };
      const sparsePoint = () => ({
        at: observedAt, x: 80, google_trends: null, combined: 80,
        observed_sources: ['x'],
      });
      const sparseWindow = () => ({
        status: 'insufficient_observed_history', points: [sparsePoint()],
        available_point_count: 1, available_from: observedAt, available_to: observedAt,
        basis: 'observed_x_google_hourly_points_only', interpolation: 'none',
        missing_point_policy: 'preserve_sparse_null_no_reuse', ranking_effect: 'none',
      });
      const initialsLogo = () => ({
        official_domain: null,
        logo_url: '', logo_render_mode: 'initials',
        logo_asset_source: 'initials_fallback', logo_asset_host: '',
        logo_asset_verification: 'initials_fallback', logo_asset_format: 'none',
        logo_asset_mime: '', logo_asset_width: 0, logo_asset_height: 0,
        logo_asset_sha256: '', logo_source_page_url: '', logo_minimum_dimension: 64,
        logo_runtime_probe_required: false, logo_rejected_asset_url: '',
        logo_asset_quality: 'fail_closed_initials_no_verified_asset',
        logo_quality_policy: 'avatar-sharpness-v1',
        logo_provenance: {
          source_page_url: null, asset_url: null, mime: null, width: 0, height: 0,
          sha256: null, verification: 'initials_fallback',
        },
      });
      const completeCard = (i) => ({
        presentation_position: i + 1,
        event_key: `e${i}`,
        selection_origin: 'canonical_validated_home_feed',
        lane: 'main',
        data_mode: 'observed_live',
        ranking_effect: 'none',
        observed_within_24h: true,
        sources: ['x'],
        trend_definition: 'verified definition',
        why_now: 'documented context',
        evidence_urls: ['https://news.example.com/context'],
        series: [{at: observedAt, source: 'x', value: 80, provenance: 'observed'}],
        visualization_series: {
          metric: 'normalized_attention_index', canonical_series_unchanged: true,
          data_mode: 'observed_sparse', interpolation: 'none', ranking_effect: 'none',
          '1w': sparseWindow(), '1m': sparseWindow(), '3m': sparseWindow(),
        },
        context_research: {
          status: 'ready', trigger_title: `trigger-${i}`, why_now: 'documented context',
          evidence_urls: ['https://news.example.com/context'],
        },
        related_keywords: Array.from({length: 5}, (_, k) => ({text: `k${k}`})),
        companies: Array.from({length: 10}, (_, c) => ({
          company: `company-${i}-${c}`,
          stock_code: `S${i}${c}`,
          exchange: 'KRX',
          company_role_category: roles[c % roles.length],
          company_role_label: 'verified role',
          company_description: 'listed company',
          connection_explanation: 'documented relation',
          ontology_complete: true,
          ontology_path: ['trend', 'role', `company-${i}-${c}`],
          evidence_sources: [{url: 'https://company.example.com/evidence'}],
          relation_tier: 'direct',
          market_snapshot: null,
          ...initialsLogo(),
        })),
        keyword_company_links: [0, 1].map((k) => ({
          keyword: `k${k}`, company: `company-${i}-${k}`,
          connection_explanation: 'documented keyword relation',
          evidence_urls: ['https://company.example.com/evidence'],
        })),
      });
      const feedFor = (items) => ({
        schema_version: 'trzip-presentation-feed-v4',
        status: items.length ? 'ready' : 'empty',
        frontend_default: true,
        observed_at: observedAt,
        selection_policy: 'validated_live_home_feed_v1',
        logo_policy: {...logoPolicy},
        transition: {...transition},
        items,
      });
      const clone = (value) => JSON.parse(JSON.stringify(value));
      const reject = (feed, code) => {
        if (api.selectLiveHomeRows({presentation_feed: feed}).eligible) process.exit(code);
      };
      for (const count of [0, 3, 10]) {
        const items = Array.from({length: count}, (_, i) => completeCard(i));
        const payload = {presentation_feed: feedFor(items)};
        const selected = api.selectLiveHomeRows(payload);
        if (!selected.eligible || selected.items.length !== count) process.exit(10 + count);
        if (count > 0) {
          const cached = api.selectLiveHomeRows(payload, {fromCache: true});
          if (cached.eligible || cached.items.length !== 0) process.exit(20 + count);
          const stale = api.selectLiveHomeRows(payload, {stale: true});
          if (stale.eligible || stale.items.length !== 0) process.exit(25 + count);
        }
      }
      const legacy = api.selectLiveHomeRows({presentation_feed: {
        schema_version: 'trzip-presentation-feed-v3',
        status: 'ready',
        frontend_default: true,
        selection_policy: 'fixed_top10_v3',
        transition: {...transition},
        items: Array.from({length: 10}, (_, i) => ({rank: i + 1})),
      }});
      if (legacy.eligible || legacy.items.length !== 0) process.exit(30);
      const synthetic = feedFor([]); synthetic.transition.synthetic_data_used = true; reject(synthetic, 31);
      reject(feedFor(Array.from({length: 11}, (_, i) => completeCard(i))), 32);
      const wrongMode = feedFor([completeCard(0)]); wrongMode.items[0].data_mode = 'observed_reference'; reject(wrongMode, 33);
      const onlyNine = completeCard(0);
      onlyNine.companies = onlyNine.companies.slice(0, 9);
      reject(feedFor([onlyNine]), 34);
      const elevenCompanies = completeCard(0);
      elevenCompanies.companies.push({
        company: 'company-extra', stock_code: 'SX', exchange: 'KRX',
        company_role_category: 'distribution', connection_explanation: 'documented relation',
      });
      reject(feedFor([elevenCompanies]), 36);
      const onlyTwoRoles = completeCard(0);
      onlyTwoRoles.companies.forEach((company, i) => {
        company.company_role_category = i % 2 ? 'distribution' : 'manufacturing_development';
      });
      const selectedTwoRoles = api.selectLiveHomeRows({presentation_feed: feedFor([onlyTwoRoles])});
      if (!selectedTwoRoles.eligible || selectedTwoRoles.items.length !== 1) process.exit(35);
      const onlyOneRole = completeCard(0);
      onlyOneRole.companies.forEach((company) => {
        company.company_role_category = 'manufacturing_development';
      });
      reject(feedFor([onlyOneRole]), 44);
      const missingContext = completeCard(0);
      missingContext.context_research.evidence_urls = [];
      reject(feedFor([missingContext]), 37);
      const missingOntology = completeCard(0);
      missingOntology.companies[0].ontology_complete = false;
      reject(feedFor([missingOntology]), 38);
      const oneLinkedKeyword = completeCard(0);
      oneLinkedKeyword.keyword_company_links = oneLinkedKeyword.keyword_company_links.slice(0, 1);
      reject(feedFor([oneLinkedKeyword]), 39);
      const reviewLane = completeCard(0); reviewLane.lane = 'review'; reject(feedFor([reviewLane]), 40);
      const staleSeries = completeCard(0);
      staleSeries.series[0].at = '2026-08-14T05:00:00.000Z';
      reject(feedFor([staleSeries]), 41);
      const longKeyword = completeCard(0); longKeyword.related_keywords[0].text = '일곱글자키워드'; reject(feedFor([longKeyword]), 42);
      const duplicateIdentity = completeCard(0);
      duplicateIdentity.companies[1].exchange = duplicateIdentity.companies[0].exchange;
      duplicateIdentity.companies[1].stock_code = duplicateIdentity.companies[0].stock_code;
      reject(feedFor([duplicateIdentity]), 43);
      const wrongTerminal = completeCard(0); wrongTerminal.companies[0].ontology_path[2] = '다른기업'; reject(feedFor([wrongTerminal]), 44);
      const brokenLogo = completeCard(0); brokenLogo.companies[0].logo_provenance.verification = 'verified_safe_svg'; reject(feedFor([brokenLogo]), 45);
      const syntheticSparse = completeCard(0); syntheticSparse.visualization_series['1w'].interpolation = 'linear'; reject(feedFor([syntheticSparse]), 46);
      for (const [field, code] of [['supplemental_display_data_used', 47], ['fallback_used', 48], ['canonical_ranking_affected', 49]]) {
        const invalidTransition = feedFor([]); invalidTransition.transition[field] = true; reject(invalidTransition, code);
      }
      const duplicateEvent = feedFor([completeCard(0), completeCard(1)]); duplicateEvent.items[1].event_key = 'e0'; reject(duplicateEvent, 50);
      const wrongPosition = feedFor([completeCard(0)]); wrongPosition.items[0].presentation_position = 2; reject(wrongPosition, 51);
      console.log('v4 fixtures 0/3/10 ok');
    """
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "v4 fixtures 0/3/10 ok" in result.stdout


def test_network_failure_cache_keeps_detail_rows_but_never_populates_live_home() -> None:
    script = r"""
      const observedAt = new Date().toISOString();
      const roles = ['manufacturing_development', 'distribution', 'retail_sales'];
      const card = {
        rank: 1,
        event_id: 'cached-event',
        display_name: '캐시 상세용 사건',
        data_mode: 'observed_live',
        context_research: {
          status: 'ready', trigger_title: 'cached trigger', why_now: 'documented context',
          evidence_urls: ['https://news.example.com/context'],
        },
        related_keywords: Array.from({length: 5}, (_, k) => ({text: `k${k}`})),
        companies: Array.from({length: 10}, (_, c) => ({
          company: `company-${c}`,
          stock_code: `S${c}`,
          exchange: 'KRX',
          company_role_category: roles[c % roles.length],
          company_description: 'listed company',
          connection_explanation: 'documented relation',
          ontology_complete: true,
          ontology_path: ['trend', 'role', `company-${c}`],
          evidence_sources: [{url: 'https://company.example.com/evidence'}],
        })),
        keyword_company_links: [0, 1].map((k) => ({
          keyword: `k${k}`, company: `company-${k}`,
          connection_explanation: 'documented keyword relation',
          evidence_urls: ['https://company.example.com/evidence'],
        })),
      };
      const publication = {
        publication_id: 'cached-publication',
        generated_at: observedAt,
        observed_at: observedAt,
      };
      const payload = {
        ...publication,
        mode: 'live',
        unified_ranking: [card],
        presentation_feed: {
          schema_version: 'trzip-presentation-feed-v4',
          status: 'ready',
          frontend_default: true,
          selection_policy: 'validated_live_home_feed_v1',
          transition: {synthetic_data_used: false, padding_forbidden: true},
          items: [card],
        },
      };
      const metadata = {...publication, mode: 'live'};
      const runtimeStatus = {...publication, mode: 'live', source_status: {
        x: 'observed', google_trends: 'observed',
      }};
      const storage = new Map();
      globalThis.localStorage = {
        getItem: (key) => storage.has(key) ? storage.get(key) : null,
        setItem: (key, value) => storage.set(key, String(value)),
      };
      localStorage.setItem('trzip:latest-intelligence:v3', JSON.stringify({
        payload, metadata, runtimeStatus,
      }));
      globalThis.fetch = async () => { throw new Error('network unavailable'); };
      require('./frontend/trendzip-data.js');
      globalThis.TRZIP_DATA_API.loadTrends().then((result) => {
        if (result.source !== 'local-cache') process.exit(41);
        if (!result.status.fromCache || !result.status.stale) process.exit(42);
        if (result.featuredTrends.length !== 0 || result.liveHomeEligible) process.exit(43);
        if (result.trends.length !== 1 || result.trends[0].displayName !== '캐시 상세용 사건') process.exit(44);
        console.log('cache home fail-closed ok');
      }).catch((error) => {
        console.error(error);
        process.exit(45);
      });
    """
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "cache home fail-closed ok" in result.stdout


def test_daily_publication_remains_current_until_next_publish_window() -> None:
    script = r"""
      require('./frontend/trendzip-data.js');
      const api = globalThis.TRZIP_DATA_API;
      const observedAt = '2026-08-15T21:00:00.000Z'; // 06:00 KST
      const payload = {observed_at: observedAt, collection_status: {source_status: {
        x: 'observed', google_trends: 'observed',
      }}};
      const metadata = {observed_at: observedAt, collection: {}};
      const runtime = {observed_at: observedAt, source_status: {
        x: 'observed', google_trends: 'observed',
      }};
      const beforeNextPublish = api.dataStatus(payload, metadata, runtime, {
        now: new Date('2026-08-16T20:59:00.000Z'),
      });
      if (beforeNextPublish.stale || beforeNextPublish.ageMinutes !== 1439) process.exit(51);
      const withinGrace = api.dataStatus(payload, metadata, runtime, {
        now: new Date('2026-08-16T22:00:00.000Z'),
      });
      if (withinGrace.stale || !withinGrace.delayed) process.exit(52);
      const afterGrace = api.dataStatus(payload, metadata, runtime, {
        now: new Date('2026-08-16T23:01:00.000Z'),
      });
      if (!afterGrace.stale) process.exit(53);
      if (api.dataContract.freshForMinutes !== 1440) process.exit(54);
      if (api.dataContract.staleAfterMinutes !== 1560) process.exit(55);
      console.log('daily publication freshness ok');
    """
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "daily publication freshness ok" in result.stdout


def test_stock_add_flow_has_search_groups_accessibility_and_broad_universe() -> None:
    assert '<script src="./mock-stock-universe.js?v=' in INDEX
    assert 'data-mk="stockopen"' in INDEX
    assert "openStockSearch = () =>" in INDEX
    assert "data-stock-search-dialog" in INDEX
    assert 'role="tablist" aria-label="거래 시장"' in INDEX
    assert 'data-stock-market-tab="domestic"' in INDEX
    assert 'data-stock-market-tab="foreign"' in INDEX
    assert 'role="tabpanel" aria-labelledby="stock-market-domestic-tab"' in INDEX
    assert "const isDomestic = (company)" in INDEX
    assert "const inMarketScope = (company)" in INDEX
    assert "syncMarketTabs(); render();" in INDEX
    assert "const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']" in INDEX
    assert "종목명, 영문명, 종목코드" in INDEX
    assert "최근 본 종목" in INDEX
    assert "인기 종목" in INDEX
    assert "검색 결과 " in INDEX
    assert "company.aliases" in INDEX
    assert "event.key !== 'Tab'" in INDEX
    assert "TRZIP_STOCK_UNIVERSE" in STOCKS
    assert STOCKS.count("stock('") >= 50
    assert "logo_minimum_dimension: 64" in STOCKS


def test_latest_motion_v2_visual_contract_is_preserved_without_data_contract_drift() -> None:
    assert 'data-zip="frame" role="button" tabindex="0"' in INDEX
    assert "frame.addEventListener('wheel'" in INDEX
    assert "frame.addEventListener('keydown'" in INDEX
    assert "['Enter', ' ', 'ArrowDown', 'PageDown']" in INDEX
    assert 'data-trend-summary-card="1"' in INDEX
    assert 'background:#F3EFFC; border-radius:22px' in INDEX
    assert 'data-freshness-card="1"' in INDEX
    assert 'background:#FAFAFC; border:1px solid #ECE8F3' in INDEX
    assert 'data-freshness-explanation="1"' in INDEX
    assert 'data-interest-card="1"' in INDEX
    assert '언급량 추이 · 관심지수' in INDEX
    assert 'data-company-role-folder="1"' in INDEX
    assert 'data-folder-toggle="1"' in INDEX
    assert 'aria-label="{{ f.title }} {{ f.count }} 기업 목록 열기 또는 접기"' in INDEX
    assert 'data-folder-body="1"' in INDEX
    assert 'data-folder-company="1"' in INDEX
    assert "@keyframes omSheetRise" in INDEX
    assert "[data-company-dialog]{animation:omSheetRise 340ms" in INDEX
    assert "[data-folder-company]:nth-child(4){animation-delay:155ms}" in INDEX
    assert "animateTrendSelection()" in INDEX
    assert "prefers-reduced-motion:reduce" in INDEX

    # 시세·시총·환율 표시는 검증된 market_snapshot만 사용하는 기존 fail-closed 계약을 유지한다.
    assert "const snapshot = company && company.market_snapshot" in INDEX
    assert "snapshot.status !== 'observed'" in INDEX
    assert "sheetHasMarketData" in INDEX
    assert "synthetic_data_used === false" in INDEX


def test_portfolio_owner_emoji_is_persisted_and_company_logos_stay_in_holdings() -> None:
    assert "emoji: String(record.emoji || '💜')" in DATA
    assert "emoji: String(input.emoji || '💜')" in DATA
    assert "emoji: String(emoji || '💜').trim()" in INDEX
    assert "portfolio.emoji || '💜'" in INDEX
    assert 'data-portfolio-avatar="owner"' in INDEX
    assert 'data-portfolio-avatar="seed-user"' in INDEX
    assert "this.escapeHtml(portfolio.emoji)" in INDEX
    assert "this.mkEditPortfolioId" in INDEX
    assert "emoji: emo" in INDEX
    assert "portfolioLogoMarkup(company" in INDEX
    assert "data-portfolio-avatar=\"owner\" role=\"img\"" in INDEX


def test_maker_controls_are_keyboard_reachable_and_hashtags_follow_six_character_contract() -> None:
    for token in (
        '<button type="button" data-mk="emoji"',
        '<button type="button" data-mk="hashadd"',
        'role="switch" aria-checked="true"',
        '<button type="button" data-mk="submit"',
        'maxlength="6"',
        '태그당 6글자',
    ):
        assert token in INDEX
    assert "tog.setAttribute('aria-checked'" in INDEX
    assert "if (t.length > 6)" in INDEX
    assert ".slice(0, 6)" in DATA


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
