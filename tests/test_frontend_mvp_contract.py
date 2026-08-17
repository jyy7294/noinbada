import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
DATA = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")
STOCKS = (ROOT / "frontend" / "mock-stock-universe.js").read_text(encoding="utf-8")
SHOWCASE_MANIFEST = json.loads((ROOT / "frontend" / "showcase" / "manifest.json").read_text(encoding="utf-8"))
SHOWCASE = json.loads((ROOT / "frontend" / "showcase" / "showcase.json").read_text(encoding="utf-8"))


def test_public_showcase_is_hash_pinned_and_has_exact_approved_shape() -> None:
    import hashlib

    payload_path = ROOT / "frontend" / "showcase" / "showcase.json"
    assert SHOWCASE_MANIFEST["mode"] == "showcase_live_simulation"
    assert SHOWCASE_MANIFEST["display_status"] == "NOW"
    assert SHOWCASE_MANIFEST["display_time_policy"] == "client_kst_floor_hour"
    assert SHOWCASE_MANIFEST["approval"]["approved_count"] == 10
    total_companies = sum(len(card["companies"]) for card in SHOWCASE["cards"])
    unique_securities = {
        company["stock_code"]
        for card in SHOWCASE["cards"]
        for company in card["companies"]
    }
    market_data = SHOWCASE_MANIFEST["market_data"]
    assert {
        key: market_data[key]
        for key in (
            "estimated", "provider", "ranking_effect", "snapshot_count",
            "status", "synthetic", "unique_security_count",
        )
    } == {
        "estimated": False,
        "provider": "pykrx+yahoo_finance",
        "ranking_effect": "none",
        "snapshot_count": total_companies,
        "status": "observed",
        "synthetic": False,
        "unique_security_count": len(unique_securities),
    }
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", market_data["latest_market_session"])
    assert market_data["refreshed_at"].endswith("Z")
    assert hashlib.sha256(payload_path.read_bytes()).hexdigest() == SHOWCASE_MANIFEST["showcase"]["sha256"]
    assert SHOWCASE["source_ranking_mode"] == "actual_full_ledger_no_recency"
    assert SHOWCASE["enrichment_mode"] == "reconstructed_demo"
    assert len(SHOWCASE["cards"]) == 10
    for order, card in enumerate(SHOWCASE["cards"], 1):
        assert card["presentation_order"] == order
        assert len(card["related_keywords"]) == 5
        assert len(card["companies"]) == 10
        assert 3 <= len({company["company_role_category"] for company in card["companies"]}) <= 4
        assert all(company["relationship_status"] == "reconstructed_demo" for company in card["companies"])
        assert all(company["market_snapshot"]["status"] == "observed" for company in card["companies"])
        assert all(len(company["market_snapshot"]["price_points"]) == 30 for company in card["companies"])
        assert all(company["market_snapshot"]["market_cap_currency"] == "KRW" for company in card["companies"])
        assert all(company["market_snapshot"]["synthetic"] is False for company in card["companies"])
        assert all(company["connection_explanation"] for company in card["companies"])
        assert all("연결 시나리오" not in company["connection_explanation"] for company in card["companies"])


def test_frontend_defaults_to_validated_showcase_without_touching_live_contract() -> None:
    assert "api.loadTrends({ mode: 'showcase' })" in INDEX
    assert "const SHOWCASE_BASE = globalThis.location?.protocol === 'file:'" in DATA
    assert "SHOWCASE_MANIFEST_URL = `${SHOWCASE_BASE}/showcase/manifest.json`" in DATA
    assert "async function loadShowcase()" in DATA
    assert "validateShowcasePayload(payload, manifest)" in DATA
    assert "sha256Hex(payloadText)" in DATA
    assert "showcase_rank_bars" in INDEX
    assert "data_provenance: 'reconstructed_demo'" in INDEX
    assert "this.liveStatus = 'NOW'" in INDEX
    assert "loadShowcase," in DATA


def test_user_ui_hides_raw_provider_names_and_source_links() -> None:
    assert "시장 정보 · {{ sheetProviderLabel }}" not in INDEX
    assert 'href="{{ sheetSourceUrl }}"' not in INDEX
    assert "시장 기준일 · {{ sheetAsOf }}" in INDEX
    assert "실제 시장 데이터 · {{ sheetAsOf }} 기준" not in INDEX
    assert "시가총액·원화" in INDEX
    assert "vals.sheetProviderLabel" not in INDEX
    assert "vals.sheetSourceUrl" not in INDEX


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
    assert "은(는)" not in INDEX


def test_share_surface_uses_native_share_real_clipboard_and_social_metadata() -> None:
    for token in (
        'property="og:title"', 'property="og:description"', 'property="og:image"',
        'name="twitter:card"', "navigator.share(payload)",
        "navigator.clipboard.writeText(url)", "document.execCommand('copy')",
        "currentSharePayload()", "base.searchParams.set('trend', eventKey)",
        "s.setAttribute('aria-label', '트렌드 공유하기')",
    ):
        assert token in INDEX
    assert "카카오톡으로 공유했어요" not in INDEX
    assert "카카오톡 공유" in INDEX
    assert "인스타그램 공유" in INDEX
    assert "메시지 공유" not in INDEX
    assert "https://cdn.simpleicons.org/kakaotalk/3C1E1E" in INDEX
    assert "https://cdn.simpleicons.org/instagram/FFFFFF" in INDEX
    assert "key === 'sms'" not in INDEX
    assert (ROOT / "frontend" / "assets" / "share" / "trzip-og.png").is_file()


def test_each_portfolio_detail_has_an_accessible_share_action_with_its_own_payload() -> None:
    assert 'data-pd="shareBtn"' in INDEX
    assert 'aria-label="밈트폴리오 공유하기"' in INDEX
    share_method = INDEX[INDEX.index("  shareWire() {") : INDEX.index("  openShare(el, sharePayload = null) {")]
    assert "this.openShare(button, this.portfolioSharePayload());" in share_method
    assert "if (s.closest('[data-pd=\"shareBtn\"]')) return;" in share_method
    payload_method = INDEX[INDEX.index("  portfolioSharePayload() {") : INDEX.index("  async copyShareLink(url) {")]
    assert "portfolio.id" in payload_method
    assert "TRZIP 밈트폴리오" in payload_method
    portfolio_render = INDEX[INDEX.index("  renderPresentationPortfolios()") : INDEX.index("  renderPortfolioDetail(portfolio)")]
    assert "new URLSearchParams(window.location.search).get('portfolio')" in portfolio_render
    assert "this.renderPortfolioDetail(sharedPortfolio);" in portfolio_render


def test_profile_editor_uses_nickname_bio_and_icon_without_a_redundant_profile_tag() -> None:
    assert 'data-profile="badge"' not in INDEX
    assert "프로필 태그" not in INDEX
    profile_methods = INDEX[INDEX.index("  profileDefaults() {") : INDEX.index("  myStats() {")]
    assert "badge:" not in profile_methods
    assert "has_badge" not in profile_methods


def test_my_page_portfolio_cards_do_not_repeat_portfolio_keywords() -> None:
    stash_method = INDEX[INDEX.index("  myAddStash(frame) {") : INDEX.index("  shareWire() {")]
    unstash_method = INDEX[INDEX.index("  removeStashedPortfolio(card, title) {") : INDEX.index("  shareWire() {")]
    created_card = INDEX[INDEX.index("      const list = portfolioApi ? null") : INDEX.index("  makerUniverse(trend) {")]
    saved_cards = INDEX[INDEX.index("  renderSavedPortfolios() {") : INDEX.index("  patchHomeLabels() {")]
    assert "const tags = q('tags')" not in stash_method
    assert 'data-my-unstash="1"' in stash_method
    assert "this.removeStashedPortfolio(card, title);" in stash_method
    assert "window.confirm" in unstash_method
    assert "delete this.stashed[title];" in unstash_method
    assert "delete this.stashedSet[title];" in unstash_method
    assert "#새로만든포트" not in created_card
    assert "this.escapeHtml(portfolio.keywords.map" not in saved_cards


def test_related_companies_lead_to_the_meme_portfolio_list() -> None:
    related_screen = INDEX[INDEX.index('id="related-companies"') : INDEX.index('id="make-port"')]
    routing_method = INDEX[INDEX.index("  trendPortfolioMatches(trend) {") : INDEX.index("  motionWire() {")]
    assert 'data-related-portfolio-action="1"' in related_screen
    assert "{{ openRelatedTrendPortfolio }}" in related_screen
    assert "this.track('trend_portfolio_list_open'" in routing_method
    assert "this.goPostList();" in routing_method
    assert "this.renderPortfolioDetail(matches[0]);" not in routing_method
    assert "this.hydrateMaker(trend.id);" not in routing_method


def test_portfolio_origin_trend_is_visually_distinguished_from_secondary_keywords() -> None:
    origin_method = INDEX[INDEX.index("  portfolioOriginKeyword(portfolio) {") : INDEX.index("  clearLegacyPortfolioSurfaces() {")]
    assert "portfolio.trend && portfolio.trend.name" in origin_method
    assert "matched || keywords[0]" in origin_method
    assert "트렌드 · " not in origin_method
    assert 'data-portfolio-origin="' in origin_method
    assert "this.portfolioKeywordChips(portfolio);" in INDEX
    assert "this.portfolioKeywordChips(portfolio, true)" in INDEX


def test_home_portfolio_summary_keeps_cta_without_repeating_company_rows() -> None:
    method = INDEX[INDEX.index("  renderPresentationPortfolios()") : INDEX.index("  renderPortfolioDetail(portfolio)")]
    assert "home.querySelectorAll('[data-mp-row],[data-portfolio-loading]')" in method
    assert "const featured = portfolios.slice().sort" in method
    assert "row.setAttribute('data-mp-row', '1')" in method
    assert "home.insertBefore(row, home.lastElementChild)" in method
    assert "featured.companies.length + '개 기업</span>'" in method
    assert "featured.companies.slice" not in method
    assert "밈트폴리오 보러가기" in INDEX


def test_home_list_view_fits_all_top_ten_without_internal_scroll() -> None:
    assert 'data-list-view2="1" style="display:none; flex-direction:column; margin:6px -16px 0; overflow:hidden; background:#FFFFFF; padding:0 20px;' in INDEX
    assert 'data-home-portfolios="1" style="visibility:hidden; margin:16px -16px 0;' in INDEX
    view_toggle = INDEX[INDEX.index("  viewToggleWire2()") : INDEX.index("  goPostList =")]
    assert "scroller.style.overflowY = 'hidden'" in view_toggle
    assert "list.style.display = isList ? 'flex' : 'none'" in view_toggle
    home_list_start = INDEX.rindex("const list = document.querySelector('[data-list-view2]');")
    home_list = INDEX[home_list_start : INDEX.index("  dialGo(label)")]
    assert "min-height:37px" in home_list
    assert 'data-list-row="1"' in home_list
    assert "font-weight:600;font-size:9.5px" in home_list
    assert "movementMarkup" in home_list
    assert "padding:5px 2px" in home_list


def test_company_sheet_never_uses_an_empty_company_information_fallback() -> None:
    assert "companyDescription(company, fallbackName = '')" in INDEX
    assert "'KT': '유무선 통신과 미디어·디지털 플랫폼 서비스를 제공하는 통신기업입니다.'" in INDEX
    assert "'월트 디즈니 컴퍼니': '영화·TV·스트리밍·테마파크 등 엔터테인먼트 사업을 운영합니다.'" in INDEX
    assert "const about = this.companyDescription(company, name);" in INDEX
    assert "기업 정보가 제공되지 않았습니다." not in INDEX


def test_dial_keyword_tap_opens_detail_without_relying_on_a_followup_click() -> None:
    method = INDEX[INDEX.index("  vdWire() {") : INDEX.index("  arcWire() {")]
    assert "const openWord = (word) =>" in method
    assert "openWord(word);" in method
    assert "el.addEventListener('click', () => openWord(el));" in method
    assert "performance.now() - lastOpenedAt < 450" in method


def test_portfolio_component_rows_open_an_in_place_company_sheet() -> None:
    detail = INDEX[INDEX.index("  renderPortfolioDetail(portfolio)") : INDEX.index("  // 밈트폴리오 종목 배지")]
    assert 'data-pd-company-row="1"' in detail
    assert "this.openPortfolioCompanySheet(this.buildSheet" in detail
    assert "openPortfolioCompanySheet(sheet, trigger)" in INDEX
    assert "data-portfolio-company-sheet-root" in INDEX
    assert "키움 종목홈으로 가기" in INDEX
    assert "closePortfolioCompanySheet" in INDEX


def test_saved_portfolio_restores_seed_company_metadata_when_reopened() -> None:
    method = INDEX[INDEX.index("  buildSavedPortfolioViews(") : INDEX.index("  renderSavedPortfolios() {")]
    assert "const seededByName" in method
    assert "seededPortfolios = this.presentationPortfolios || this.buildPresentationPortfolios()" in method
    assert "currentByName.get(name) || seededByName.get(name)" in method
    assert "return reference ? { ...company, ...reference } : company;" in method


def test_portfolio_list_uses_keyword_chips_without_company_name_summary() -> None:
    method = INDEX[INDEX.index("  renderPresentationPortfolios()") : INDEX.index("  renderPortfolioDetail(portfolio)")]
    assert "const keywordChips = this.portfolioKeywordChips(portfolio);" in method
    assert 'data-portfolio-keywords="1"' in method
    assert "const companyNames" not in method
    assert "portfolio.companies.slice(0, 5)" not in method


def test_portfolio_list_defaults_to_latest_and_home_feature_uses_likes() -> None:
    method = INDEX[INDEX.index("  renderPresentationPortfolios()") : INDEX.index("  renderPortfolioDetail(portfolio)")]
    sorting = INDEX[INDEX.index("  applySort() {") : INDEX.index("  snsWire() {")]
    assert "최신순</button>" in INDEX
    assert "좋아요순</button>" in INDEX
    assert "수익률순</button>" in INDEX
    assert "가장 많이 반응한 밈트폴리오" in method
    assert "Number(b.likes || 0) - Number(a.likes || 0)" in method
    assert 'data-likes="' in method
    assert "mode === 1 ? b.likes - a.likes : mode === 2 ? b.ret - a.ret : b.date - a.date" in sorting


def test_portfolio_detail_does_not_show_a_top_percentile_badge() -> None:
    assert "TOP 5%" not in INDEX


def test_trend_icons_prefer_specific_context_over_generic_categories() -> None:
    icon_method = INDEX[INDEX.index("  trendIconMeta(name, category = '') {") : INDEX.index("  syncStatusClock(")]
    assert "/대한독립만세|광복절|독립운동/, '1f1f0-1f1f7'" in icon_method
    assert "/메츠|브레이브스|한화\\s*(vs|대)\\s*삼성|삼성\\s*(vs|대)\\s*한화|야구/, '26be'" in icon_method
    assert "/맨유|리즈|데포르티보|레알\\s*마드리드|축구/, '26bd'" in icon_method
    assert "/UFC|격투기|MMA/, '1f94a'" in icon_method
    assert "/그래미|음악|콘서트|공연/, '1f3b5'" in icon_method


def test_interest_range_tabs_remain_selectable_when_a_long_period_is_sparse() -> None:
    render_vals = INDEX[INDEX.index("  renderVals() {") : INDEX.index("    return vals;")]
    assert "vals['range' + i] = this.rangeStyle(this.state.range === i, true);" in render_vals
    assert "vals['rangeDisabled' + i] = 'false';" in render_vals
    assert "if (!rangeAvailability[i]) return;" not in render_vals
    assert "this.setState({ range: i, interestPoint: null }, () => this.animateInterestRange());" in render_vals


def test_freshness_is_not_derived_from_the_selected_range() -> None:
    assert 'data-interest-card="1"' not in INDEX
    assert 'data-interest-point-buttons="1"' not in INDEX
    assert "day: '진입 ' + (elapsedDays + 1) + '일차'" in INDEX
    assert "day: '진입 ' + days + '일차'" in INDEX
    assert "'대한민국 광복절': { observedAt: '2026-08-15T00:00:00+09:00', captureDays: 0, expansionDays: 1 }" in INDEX
    render_vals = INDEX[INDEX.index("  renderVals() {") : INDEX.index("    return vals;")]
    assert 'const freshnessChart = this.buildInterestCurve(curTrend, 0);' in render_vals
    assert 'const relativeInterestValues = (freshnessChart.values || []).filter(Number.isFinite);' in render_vals
    assert '대중화 단계는 기간 고점(100)을 찍고 유지하거나 내려오는 흐름까지 함께 봅니다.' not in INDEX


def test_home_shows_the_observed_timestamp_only_once() -> None:
    header = INDEX[INDEX.index('data-screen-label="01 홈"') : INDEX.index('data-vd-stage="1"')]
    assert "{{ liveObservedAt }}" not in header
    assert 'data-home-observed="1"' in header


def test_home_header_uses_a_live_title_and_explicit_dial_list_controls() -> None:
    header = INDEX[INDEX.index('data-screen-label="01 홈"') : INDEX.index('data-vd-stage="1"')]
    assert "실시간 트렌드</div>" in header
    assert 'aria-label="키움증권으로 돌아가기"' in header
    assert 'onClick="{{ openKiwoomHome }}"' in header
    assert 'src="assets/trzip-logo.png"' not in header
    assert 'data-view-btn2="dial"' in header
    assert 'data-view-btn2="list"' in header
    toggle = INDEX[INDEX.index("  viewToggleWire2() {") : INDEX.index("  goPostList =")]
    assert "const setView = (nextIsList) =>" in toggle
    assert "dialBtn.addEventListener('click', () => setView(false));" in toggle
    assert "listBtn.addEventListener('click', () => setView(true));" in toggle


def test_home_title_has_no_extra_selection_criteria_help_button() -> None:
    header = INDEX[INDEX.index('data-screen-label="01 홈"') : INDEX.index('data-vd-stage="1"')]
    assert 'data-home-selection-guide="1"' not in header
    assert 'aria-label="트렌드 선정 기준 보기"' not in header


def test_freshness_information_icon_and_relation_cta_keep_a_simple_purpose() -> None:
    assert 'data-info-trigger="freshness"' in INDEX
    assert 'aria-label="트렌드 신선도 기준 보기"' in INDEX
    assert 'data-info-trigger="relations"' not in INDEX
    assert "infoTopics()" in INDEX
    assert "openInfoSheet(topicKey = 'selection')" in INDEX
    assert "data-info-sheet-root" in INDEX
    assert "__trzipInfoSheetOpen" in INDEX
    assert "관련기업 보러가기" in INDEX
    assert "관련기업 연결 기준" not in INDEX
    assert "왜 이 기업인가" not in INDEX
    assert "트렌드 → 연결 역할 → 기업 정보" not in INDEX
    assert "역할과 연결 근거를 확인하고 종목 정보로 이어집니다." not in INDEX


def test_dial_keeps_korean_trend_titles_in_the_left_readable_zone() -> None:
    dial_markup = INDEX[INDEX.index('data-vd-stage="1"') : INDEX.index('data-home-empty="1"')]
    assert 'data-vd-focus-copy="1"' in dial_markup
    assert "left:56px; top:50%; z-index:20; width:218px" in dial_markup
    assert "text-align:left" in dial_markup
    assert "white-space:nowrap" in dial_markup
    assert "text-overflow:ellipsis" in dial_markup
    assert "overflow-wrap:anywhere" not in dial_markup
    home_projection = INDEX[INDEX.index("if (top) document.querySelectorAll('[data-vd-big]')") : INDEX.index("groups.forEach((els) =>")]
    assert "label.length >= 18 ? '20px'" in home_projection


def test_home_dial_keeps_its_center_title_in_sync_without_overlaying_the_selected_node() -> None:
    patch = INDEX[INDEX.index("  patchHomeLabels() {") : INDEX.index("  dialGo(label) {")]
    vd = INDEX[INDEX.index("  vdWire() {") : INDEX.index("  arcWire() {")]
    assert "(window.__omPaints || []).forEach((paint) => paint())" in patch
    assert "dot.style.visibility = isSel ? 'hidden' : 'visible';" in vd
    assert "const nodeX = Math.max(218, Math.min(278, width - 320));" in vd
    assert "const trendIndex = Number(activeWords[best].dataset.trendIndex);" in vd


def test_home_dial_hides_repeated_labels_without_losing_the_matching_trend() -> None:
    patch = INDEX[INDEX.index("  patchHomeLabels() {") : INDEX.index("  dialGo(label) {")]
    assert "const seenDialLabels = new Set();" in patch
    assert "seenDialLabels.has(labelKey)" in patch
    assert "el.dataset.trendIndex = String(i);" in patch


def test_home_dial_stays_hidden_until_its_first_published_label_is_ready() -> None:
    dial_markup = INDEX[INDEX.index('data-vd-stage="1"') : INDEX.index('data-home-empty="1"')]
    assert 'data-home-ready="false"' in dial_markup
    assert "opacity:0; pointer-events:none; transition:opacity 180ms ease" in dial_markup
    patch = INDEX[INDEX.index("  patchHomeLabels() {") : INDEX.index("  dialGo(label) {")]
    assert "dialStage.dataset.homeReady = 'true';" in patch
    assert "dialStage.style.pointerEvents = 'auto';" in patch
    assert "dialStage.style.opacity = '1';" in patch


def test_home_dial_keywords_open_their_trend_without_a_rotation_detour() -> None:
    dial = INDEX[INDEX.index("  dialGo(label) {") : INDEX.index("  mpRotateWire() {")]
    vd = INDEX[INDEX.index("  vdWire() {") : INDEX.index("  arcWire() {")]
    orbit = INDEX[INDEX.index("  dialWire() {") : INDEX.index("  viewToggleWire() {")]
    assert "stage.__selectTrend" not in dial
    assert "if (!this.trends.length || this.trends[0].emptyState) return;" in dial
    assert "const openWord = (word) =>" in vd
    assert "this.dialGo(word.getAttribute('data-label') || word.textContent);" in vd
    assert "if (bigHit) {" in vd
    assert "this.dialGo(el.getAttribute('data-label'));" in orbit
    assert "rot = -(i / N)" not in orbit
    assert "if (rows.length < 2 || window.__mpRotate) return;" in INDEX


def test_app_starts_with_zipper_and_uses_a_single_handoff_to_home() -> None:
    shell = INDEX[INDEX.index("  protoShell() {") : INDEX.index("  componentDidMount() {")]
    mount = INDEX[INDEX.index("  componentDidMount() {") : INDEX.index("  componentWillUnmount() {")]
    zipper = INDEX[INDEX.index("  zipWire() {") : INDEX.index("  listViewWire() {")]
    assert "var idx = 0;" in shell
    assert "window.__zipOpening" in shell
    assert "this.zipWire()" in mount
    assert "window.__zipOpening = true;" in zipper


def test_home_featured_portfolio_returns_to_the_portfolio_list() -> None:
    handler = INDEX[INDEX.index("  goHomePost = (e) => {") : INDEX.index("  panTo(t) {")]
    assert "this.pdFrom = 'home';" not in handler
    assert handler.count("this.pdFrom = 'list';") == 2


def test_portfolio_detail_back_restores_the_screen_that_opened_it() -> None:
    handler = INDEX[INDEX.index("  pdBack = () => {") : INDEX.index("  goHomePost = (e) => {")]
    assert "this.pdFrom === 'my' ? '#my-page'" in handler
    assert "this.pdFrom === 'companies' ? '#related-companies' : '#post-list'" in handler
    assert "this.panTo(document.querySelector(destination));" in handler


def test_home_header_prioritizes_the_live_trend_title() -> None:
    header = INDEX[INDEX.index('data-screen-label="01 홈"') : INDEX.index('data-vd-stage="1"')]
    assert "실시간 트렌드</div>" in header
    assert 'aria-label="키움증권 열기" onClick="{{ openKiwoomHome }}"' not in header
    assert "openKiwoomHome = () =>" in INDEX
    assert "window.open('https://www.kiwoom.com/', '_blank', 'noopener,noreferrer');" in INDEX


def test_critical_mobile_controls_have_accessible_touch_targets() -> None:
    assert INDEX.count('data-critical-touch-target="1"') >= 3
    assert "min-width:44px; height:44px" in INDEX
    assert "width:44px;height:44px;margin:-6px" in INDEX
    assert '[data-critical-touch-target]:focus-visible' in INDEX
    assert 'aria-label="트렌드를 목록으로 보기"' in INDEX
    assert 'aria-pressed="false"' in INDEX
    assert "btn.setAttribute('aria-pressed', String(isList))" in INDEX
    assert "width:32px;height:32px" not in INDEX


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
    assert "this.logoFailures.has(name + '|' + candidate)" in INDEX
    assert "return candidate;" in INDEX
    assert "warmCompanyLogos()" in INDEX
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
    assert "if (this.logoFailures.has(failureKey) || this.companyDomains[name] === logoUrl) return;" in INDEX
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
        const p = row.logo_provenance || {};
        if (row.logo_asset_scope !== 'maker_stock_search') throw new Error(row.id + ': scope');
        if (row.logo_render_mode !== 'image') throw new Error(row.id + ': image mode');
        if (row.logo_runtime_probe_required !== false) throw new Error(row.id + ': runtime probe');
        if (!/^https:\/\//.test(row.logo_url) || !/^https:\/\//.test(row.logo_source_page_url)) throw new Error(row.id + ': url');
        if (!/^[0-9a-f]{64}$/.test(row.logo_asset_sha256)) throw new Error(row.id + ': sha');
        if (row.logo_asset_format === 'svg') {
          if (row.logo_asset_verification !== 'verified_safe_svg') throw new Error(row.id + ': svg verification');
        } else if (!((row.logo_asset_width >= 64 && row.logo_asset_height >= 64
          && row.logo_asset_verification === 'verified_raster_min_64px')
          || (row.logo_asset_width >= 64 && row.logo_asset_height >= 32
          && row.logo_asset_verification === 'verified_raster_wordmark'))) {
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


def test_interest_chart_uses_published_display_windows_and_preserves_gaps() -> None:
    assert "buildInterestCurve(trend, rangeIndex = 0)" in INDEX
    assert "const rangeKey = ['24h', '1w'][Math.max(0, Math.min(1, rangeIndex))]" in INDEX
    assert "const displayRangeLabel = rangeSpec.label;" in INDEX
    assert "showcaseAllHistory ? '전체'" not in INDEX
    assert "trend.visualizationSeries" in INDEX
    assert "visualization[rangeSpec.sourceKey]" in INDEX
    assert "publishedWindow && publishedWindow.points" in INDEX
    assert "chartPoints.map((point) => point.combined)" in INDEX
    assert "visualization.data_mode === 'rank_responsive_display'" in INDEX
    assert "const formulaVersion = 'observed-rank-response-v2'" in INDEX
    assert "visualization.formula_version === formulaVersion" in INDEX
    assert "visualization.display_only === true" in INDEX
    assert "sameContractValue(visualization.derivation, expectedDerivation)" in INDEX
    assert "sameContractValue(visualization.presentation_rank_movement, visibleRankMovement)" in INDEX
    assert "'24h': { sourceKey: '1w'" in INDEX
    assert "pattern: 'published_series'" in INDEX
    assert "const usable = rawValues.filter(Number.isFinite)" in INDEX
    assert "if (usable.length < 2)" in INDEX
    assert "available: false" in INDEX
    assert "const MAX_CONTIGUOUS_GAP_MS = 90 * 60 * 1000" in INDEX
    assert "rangeKey === '24h'" in INDEX
    assert "publishedWindow && publishedWindow.status === 'measured'" in INDEX
    assert "this.publishedView && this.publishedView.observedAt" in INDEX
    assert "const firstTimestamp = windowStartMs" in INDEX
    assert "const lastTimestamp = windowEndMs" in INDEX
    assert "currentTimestamp - previousTimestamp > MAX_CONTIGUOUS_GAP_MS" in INDEX
    assert "segments.filter((segment) => segment.length >= 2).map" in INDEX
    assert "segments.filter((segment) => segment.length === 1)" in INDEX
    assert 'data-interest-single-points="1"' not in INDEX
    assert 'data-interest-observation-points="1"' not in INDEX
    assert "interestScaleDescription" in INDEX
    assert "scaleMax" in INDEX
    assert "scaleMid" in INDEX
    assert 'data-interest-summary="1"' not in INDEX
    assert "const observationPoints = points.filter(Boolean)" in INDEX
    assert "peak: Math.round(peakValue)" in INDEX
    assert "observationCount" in INDEX
    assert "30 + (timestamp - firstTimestamp) * 258" in INDEX
    assert '<img src="{{ opt.optIconUrl }}"' not in INDEX
    assert 'data-trend-icon-src="{{ opt.optIconUrl }}"' in INDEX
    assert "patchTrendSwitcherIcons()" in INDEX
    assert 'id="interest-chart-disclosure"' not in INDEX
    assert "Intl.DateTimeFormat('ko-KR'" in INDEX
    assert "else if (activeSegment.length)" in INDEX
    assert "barPoints" in INDEX
    for synthetic_token in ("event_ramp", "lateBreakout", "middleDip", "lateRebound", "periodProfile"):
        assert synthetic_token not in INDEX
    assert "선택한 기간의 관심 흐름을 비교해 볼 수 있습니다." not in INDEX
    assert "0~100 표시지수" not in INDEX
    assert "patchInterestChart()" in INDEX
    assert "sourceSignals" not in INDEX
    assert "sourceLabels" not in INDEX
    assert "if (!window || window.percent == null) return '—';" in INDEX
    assert "if (!Number.isFinite(value)) return '—';" in INDEX
    assert "item.attentionLift && item.attentionLift.label ? item.attentionLift.label : '—'" in INDEX
    assert "return '0.0%'" not in INDEX
    assert "출처 미확인" not in INDEX
    assert "displayOnly: true" not in INDEX
    assert "buildChartPanels(" not in INDEX
    assert "chartRevealWire()" not in INDEX
    chart_builder = INDEX[INDEX.index("  buildInterestCurve(trend, rangeIndex = 0)"):INDEX.index("  rankResponsiveInterestStyle(trend)")]
    assert "trend.series" not in chart_builder
    assert "market_snapshot" not in chart_builder
    assert "marketSnapshot" not in chart_builder
    assert "marketCap" not in chart_builder
    assert "presentationPortfolios" not in chart_builder
    assert "seed_meme_portfolio" not in chart_builder


def test_interest_chart_rank_response_uses_published_values_and_ranked_motion() -> None:
    for token in (
        "rank-responsive-presentation-v2",
        "seriesContract: 'backend_rank_responsive_display'",
        "frontendValueTransform: 'period_relative_minmax_0_100'",
        "publishedValuesConsumedDirectly: false",
        "rankStyleAffected: true",
        "rankMotionAffected: true",
        "gapsPreserved: true",
        "dataset.interestSeriesContract",
        "animateRankResponsiveInterest(root, chart)",
        "this.prefersReducedMotion()",
        "data-interest-flow-dot",
        "chart.rangeKey !== '24h'",
        "transform: 'scale(.25)'",
        "Math.min(index * rankStyle.pointStaggerMs, 420)",
        "data-interest-flow",
        "data-interest-flow-line",
        "strokeDasharray",
        "getTotalLength",
    ):
        assert token in INDEX

    script = r"""
      const fs = require('fs');
      const html = fs.readFileSync('./frontend/index.html', 'utf8');
      const match = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/);
      const Component = new Function('DCLogic', match[1] + ';return Component;')(
        class { forceUpdate() {} }
      );
      const component = new Component();
      const points = [0, 30, 60].map((minute, index) => ({
        at: new Date(Date.UTC(2026, 7, 15, 0, minute)).toISOString(),
        x: null, google_trends: [70, 83, 91][index], combined: [70, 83, 91][index],
        observed_sources: ['google_trends']
      }));
      const windowFor = (rows) => ({
        points: rows, interpolation: 'none',
        missing_point_policy: 'preserve_sparse_null_no_reuse', ranking_effect: 'none'
      });
      const visualizationSeries = {
        data_mode: 'observed_sparse', interpolation: 'none',
        canonical_series_unchanged: true, ranking_effect: 'none',
        '1w': windowFor(points), '1m': windowFor(points), '3m': windowFor(points)
      };
      const first = component.buildInterestCurve({rank: 1, visualizationSeries}, 0);
      const firstLabel = component.buildInterestCurve({rank: '1위', visualizationSeries}, 0);
      const tenth = component.buildInterestCurve({rank: 10, visualizationSeries}, 0);
      const geometry = (chart) => JSON.stringify({
        values: chart.values,
        linePath: chart.linePath,
        area: chart.area,
        points: chart.observationPoints,
        labels: chart.labels
      });
      if (geometry(first) !== geometry(tenth)) {
        throw new Error('rank changed chart values, timestamps, or geometry');
      }
      if (!(first.rankStyle.strokeWidth > tenth.rankStyle.strokeWidth)
        || !(first.rankStyle.latestMarkerRadius > tenth.rankStyle.latestMarkerRadius)
        || !(first.rankStyle.animationDurationMs < tenth.rankStyle.animationDurationMs)) {
        throw new Error('rank did not change visual response monotonically');
      }
      if (JSON.stringify(first.rankStyle) !== JSON.stringify(firstLabel.rankStyle)) {
        throw new Error('rendered rank label did not resolve to the same responsive style');
      }
      if (first.rankStyle.seriesContract !== 'backend_rank_responsive_display'
        || first.rankStyle.frontendValueTransform !== 'period_relative_minmax_0_100'
        || first.rankStyle.publishedValuesConsumedDirectly
        || !first.rankStyle.rankStyleAffected
        || !first.rankStyle.rankMotionAffected
        || !first.rankStyle.gapsPreserved) {
        throw new Error('rank-responsive presentation policy is not fail-closed');
      }
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_showcase_interest_bars_are_deterministic_rank_specific_and_not_user_labeled_demo() -> None:
    assert "showcase-rank-bars-v3" in INDEX
    assert "deterministic_rank_band_bar_profile" in INDEX
    assert "chart_type: 'bar'" in INDEX
    assert "Math.sin" not in INDEX[INDEX.index("  buildShowcaseVisualization("):INDEX.index("  async loadPublishedData()")]
    for exposed_copy in ("시연용 파생 데이터", "시연용 관심지수", "재구성 관심지수"):
        assert exposed_copy not in INDEX

    script = r"""
      const fs = require('fs');
      const html = fs.readFileSync('./frontend/index.html', 'utf8');
      const match = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/);
      const Component = new Function('DCLogic', match[1] + ';return Component;')(
        class { forceUpdate() {} }
      );
      const component = new Component();
      const at = '2026-08-16T10:00:00+09:00';
      const rows = Array.from({length: 10}, (_, index) => component.buildShowcaseVisualization({
        event_key: 'event-' + (index + 1), presentation_order: index + 1
      }, at));
      const again = component.buildShowcaseVisualization({event_key: 'event-1', presentation_order: 1}, at);
      if (JSON.stringify(rows[0]) !== JSON.stringify(again)) throw new Error('showcase bars are not deterministic');
      if (!rows.every((row) => row.data_mode === 'showcase_rank_bars'
        && row.chart_type === 'bar' && row['1w'].points.length === 16
        && row['1w'].points.every((point) => point.combined >= 0 && point.combined <= 100))) {
        throw new Error('showcase bar contract failed');
      }
      const signatures = new Set(rows.map((row) => row['1w'].points.map((point) => point.combined).join(',')));
      if (signatures.size !== 10) throw new Error('rank-specific bar profiles are duplicated');
      const current = rows.map((row) => row['1w'].points.at(-1).combined);
      if (!(current[0] > current[9])) throw new Error('published rank did not affect demo interest level');
      const terminalPeaks = rows.filter((row) => {
        const values = row['1w'].points.map((point) => point.combined);
        return values.at(-1) === Math.max(...values);
      });
      if (terminalPeaks.length === rows.length) {
        throw new Error('every showcase interest curve ends at its peak');
      }
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_interest_chart_prefers_rank_responsive_backend_windows_for_available_ranges() -> None:
    script = r"""
      const fs = require('fs');
      const html = fs.readFileSync('./frontend/index.html', 'utf8');
      const match = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/);
      const Component = new Function('DCLogic', match[1] + ';return Component;')(
        class { forceUpdate() {} }
      );
      const component = new Component();
      const base = Date.UTC(2026, 7, 15, 5);
      const rankMovement = {
        current_rank: 2, previous_rank: 4, delta: 2,
        status: 'up', label: '▲2', basis: 'previous_published_presentation_feed'
      };
      const derivation = {
        formula: 'mean_by_observed_source(weighted_sum(source_rank_position,rank_change,observation_persistence,presentation_position))',
        input_fields: [
          'observed_source_rank', 'observed_source_rank_change',
          'observation_persistence', 'presentation_position',
          'previous_published_presentation_position'
        ],
        missing_component_policy: 'neutral_50_for_unavailable_rank_change',
        neutral_rank_change_index: 50.0, formula_weight_sum: 1.0,
        display_only: true, canonical_ranking_effect: 'none',
        display_rank_effect: 'display_value_only', market_data_affected: false,
        canonical_series_unchanged: true,
        missing_point_policy: 'preserve_sparse_null_no_reuse'
      };
      const points = (values, stepHours) => values.map((combined, index) => ({
        at: new Date(base - ((values.length - 1 - index) * stepHours * 3600000)).toISOString(),
        x: combined, google_trends: null, combined, observed_sources: ['x'],
        source_components: {x: {display_index: combined}},
        observation_density: 0.5, formula_version: 'observed-rank-response-v2',
        display_only: true, canonical_ranking_effect: 'none',
        display_rank_effect: 'display_value_only', market_data_affected: false,
        ranking_effect: 'none'
      }));
      const windowFor = (rows) => ({
        status: 'measured', points: rows, display_only: true,
        formula_version: 'observed-rank-response-v2', canonical_ranking_effect: 'none',
        display_rank_effect: 'display_value_only', market_data_affected: false,
        interpolation: 'none', missing_point_policy: 'preserve_sparse_null_no_reuse',
        ranking_effect: 'none'
      });
      const visualizationSeries = {
        metric: 'normalized_attention_index',
        data_mode: 'rank_responsive_display', interpolation: 'none',
        canonical_series_unchanged: true, display_only: true,
        formula_version: 'observed-rank-response-v2',
        formula_weights: {
          source_rank_position: 0.45, rank_change: 0.20,
          observation_persistence: 0.15, presentation_position: 0.20
        },
        derivation, presentation_position: 2, presentation_rank_movement: rankMovement,
        canonical_ranking_effect: 'none', display_rank_effect: 'display_value_only',
        market_data_affected: false, ranking_effect: 'none',
        '1w': windowFor(points([15, 40, 80], 20))
      };
      const trend = {
        rank: 2, rankMovement, visualizationSeries,
        series: [{at: new Date(base).toISOString(), value: 99, source: 'x', provenance: 'observed'}]
      };
      const charts = [0, 1].map((range) => component.buildInterestCurve(trend, range));
          if (charts.map((chart) => chart.current).join(',') !== '100,100') {
            throw new Error('frontend did not normalize each display window to its relative peak');
      }
      if (charts.map((chart) => chart.observationCount).join(',') !== '2,3') {
        throw new Error('display window point counts were recomputed from raw series');
      }
      if (charts.map((chart) => chart.sourceWindowKey).join(',') !== '1w,1w') {
        throw new Error('rank-responsive windows did not take precedence');
      }
      if (charts.some((chart) => chart.displaySeriesMode !== 'rank_responsive_display')) {
        throw new Error('rank-responsive display contract was not retained');
      }
          if (charts[0].values.join(',') !== '0,100'
            || charts[0].sourceValues.join(',') !== '40,80') {
            throw new Error('24-hour tab did not preserve source points before relative scaling');
      }
      if (!(charts[0].observationPoints[0][0] > 8)) {
        throw new Error('24-hour time axis stretched sparse points to the full chart width');
      }
      if (Object.hasOwn(visualizationSeries, '24h')) {
        throw new Error('frontend fixture reintroduced a backend 24h window');
      }
      const anchoredSeries = JSON.parse(JSON.stringify(visualizationSeries));
      anchoredSeries['1w'] = windowFor(points([60, 80], 2));
      component.publishedView = {
        observedAt: new Date(base + 19 * 3600000).toISOString()
      };
      const anchoredChart = component.buildInterestCurve({
        rank: 2, rankMovement, visualizationSeries: anchoredSeries
      }, 0);
          if (!anchoredChart.available || anchoredChart.values.join(',') !== '0,100'
            || anchoredChart.sourceValues.join(',') !== '60,80'
        || !(anchoredChart.lastX < 100)) {
        throw new Error('feed observed_at did not preserve the trailing unobserved gap');
      }
      component.publishedView = null;
      const recentOnlySeries = JSON.parse(JSON.stringify(visualizationSeries));
      recentOnlySeries['1w'] = windowFor(points([60, 70, 80], 2));
      const recentOnlyTrend = {rank: 2, rankMovement, visualizationSeries: recentOnlySeries};
      if (component.buildInterestCurve(recentOnlyTrend, 1).available) {
        throw new Error('recent-only points were presented as a one-week trend');
      }
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_public_copy_and_observed_timeline_javascript_regression() -> None:
    script = r"""
      const fs = require('fs');
      const html = fs.readFileSync('./frontend/index.html', 'utf8');
      const match = html.match(/<script[^>]*data-dc-script[^>]*>([\s\S]*?)<\/script>/);
      const Component = new Function('DCLogic', match[1] + ';return Component;')(
        class { forceUpdate() {} }
      );
      const component = new Component();
      const copy = component.publicConnectionCopy({
        company: '동원산업', company_role_label: '제조·개발',
        connection_explanation: "동원산업은(는) '제조·개발' 역할 후보입니다. 실제 연결 근거입니다.",
        matched_keywords: ['삼계탕', '간편식']
      });
      if (/후보|보강\s*중|은\(는\)/.test(copy) || !copy.includes('실제 연결 근거입니다.')) {
        throw new Error('internal company state leaked into public copy: ' + copy);
      }
      const factual = component.publicConnectionCopy({
        company: 'CJ제일제당', company_role_label: '배급·유통',
        reason: '홈플러스 납품 재개를 검토 중이라고 보도됐습니다.'
      });
      if (!factual.includes('납품 재개를 검토 중')) throw new Error('factual review wording was removed');

      const values = [45, 2, 3, 4, 1, 1, 1];
      const points = values.map((value, index) => ({
        at: new Date(Date.UTC(2026, 7, 15, index * 4)).toISOString(),
        x: null, google_trends: value, combined: value,
        observed_sources: ['google_trends']
      }));
      const windowFor = () => ({
        points, interpolation: 'none',
        missing_point_policy: 'preserve_sparse_null_no_reuse', ranking_effect: 'none'
      });
      const visualizationSeries = {
        data_mode: 'observed_sparse', interpolation: 'none',
        canonical_series_unchanged: true, ranking_effect: 'none',
        '1w': windowFor(), '1m': windowFor(), '3m': windowFor()
      };
      const chart = component.buildInterestCurve({visualizationSeries}, 0);
          if (!chart.available || chart.peak !== 100 || chart.current !== 0
        || chart.observationCount !== 7 || chart.observationPoints.length !== 7) {
        throw new Error('observed timeline summary is incorrect');
      }
      if (chart.linePath !== '' || chart.area !== '') {
        throw new Error('four-hour gaps were interpolated');
      }
      const labels = chart.labels.filter(Boolean);
      if (labels.length !== 3 || new Set(labels).size !== labels.length || labels.some((label) => !label.includes(':'))) {
        throw new Error('timeline labels are duplicated or omit time: ' + JSON.stringify(labels));
      }
      if (chart.observationPoints[0][0] < 8 || chart.observationPoints.at(-1)[0] > 288) {
        throw new Error('edge observation marker can be clipped');
      }
    """
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


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
    assert "이번 트렌드와 만나는 지점" in INDEX
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
    assert "30일 주가 추이 · {{ sheetPriceCurrency }}" in INDEX
    assert "30일 주가 추이 · {{ sheetPriceCurrency }} · {{ sheetAsOf }} 기준" not in INDEX
    assert "formatMarketCap(snapshot.market_cap)" not in INDEX
    assert "snapshot.market_cap_label" not in INDEX


def test_market_snapshot_guard_rejects_unverified_values_and_preserves_real_zero_roe() -> None:
    guard_methods = INDEX[
        INDEX.index("  verifiedMarketSnapshot(company) {"):
        INDEX.index("  signedPercent(value) {")
    ]
    company_description = INDEX[
        INDEX.index("  companyDescription(company, fallbackName = '') {"):
        INDEX.index("  buildSheet(initial, name, desc, i, icon, company = {}) {")
    ]
    build_sheet = INDEX[
        INDEX.index("  buildSheet(initial, name, desc, i, icon, company = {}) {"):
        INDEX.index("\n  snsRoot()", INDEX.index("  buildSheet(initial, name, desc, i, icon, company = {}) {"))
    ]
    script = f"""
      class Guard {{
        companyLogo() {{ return ''; }}
        resolveStockUniverseCompany(company) {{ return company; }}
        normalizedCompanyMarket(company) {{ return company.market || company.exchange || ''; }}
        publicConnectionCopy(company, fallback) {{ return fallback; }}
        {guard_methods}
        {company_description}
        {build_sheet}
      }}
      const guard = new Guard();
      const observed = {{market_snapshot: {{
        status: 'observed', provider: 'yahoo_finance', as_of: '2026-08-15',
        source_url: 'https://example.com/market', price_source_url: 'https://example.com/price', currency: 'USD',
        last_price: 100, change_percent: null, price_series: Array.from({{length: 30}}, (_, i) => 90 + i),
        display_only: true, ranking_effect: 'none',
        per: null, per_status: 'unavailable_not_reported', pbr: null, roe: 0,
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
      if (sheet.per !== '미제공' || sheet.pbr !== '—' || sheet.roe !== '0.0%') process.exit(15);
      if (sheet.priceCurrency !== 'USD' || !sheet.price.includes('$')) process.exit(16);

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
    assert "label.length >= 18 ? '20px'" in INDEX
    assert 'title="{{ trendName }}"' in INDEX
    assert "nameStyle: 'flex:1; min-width:0;" in INDEX


def test_portfolio_surfaces_render_approved_demo_seeds_on_home_start() -> None:
    assert 'data-home-portfolios="1" style="visibility:hidden;' in INDEX
    assert 'data-portfolio-feed="1" style="visibility:hidden;' in INDEX
    assert "clearLegacyPortfolioSurfaces();" in INDEX
    component_mount = INDEX[INDEX.index("  componentDidMount() {") : INDEX.index("  componentWillUnmount() {")]
    assert component_mount.index("this.clearLegacyPortfolioSurfaces();") < component_mount.index("this.renderPresentationPortfolios();")
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
        "둠스데이 개봉 전, 마블 라인업만 담았다",
        "말복엔 삼계탕보다 복날 장보기",
    ):
        assert title in INDEX
    assert "companiesFromLiveTrend('둠스데이'" in INDEX
    assert "companiesFromLiveTrend('말복'" in INDEX
    assert "초콜릿 원재료 쪽으로 파봤습니다" not in INDEX
    assert "이름 안 겹쳐도 수혜주는 따로 있다" not in INDEX
    for company in ("원익", "리브스메드", "두산", "바이넥스", "한국콜마", "오리온", "CJ제일제당", "대한제분"):
        assert company in INDEX
    assert "dataMode: 'seed_portfolio'" in INDEX
    assert "좋아요순" in INDEX
    assert "수익률순" in INDEX
    assert "내 포트 수익률" not in INDEX
    assert "추천순" not in INDEX
    assert "등락순" not in INDEX


def test_seed_meme_portfolios_do_not_present_unverified_unlisted_companies() -> None:
    seed_block = INDEX.split("buildPresentationPortfolios()", 1)[1].split(
        "portfolioLogoMarkup", 1
    )[0]
    assert "const observedSnapshot" in seed_block
    assert "status: 'observed'" in seed_block
    assert "synthetic: false" in seed_block
    assert "ranking_effect: 'none'" in seed_block
    assert "price_series" in seed_block
    assert "listing_status: 'unlisted'" not in seed_block
    assert "'리브스메드': { stock_code: '491000', market: 'KOSDAQ'" in seed_block
    assert "company('제나텍'" not in seed_block


def test_saved_company_watchlist_migrates_to_canonical_listing_and_logo_snapshot() -> None:
    assert "trzip_company_watchlist_v2" in INDEX
    assert "serialized !== null" in INDEX
    assert "trzip_company_watchlist_v1" in INDEX  # one-way migration input
    assert "resolveStockUniverseCompany" in INDEX
    assert "normalizedCompanyMarket" in INDEX
    assert "current_listed === false" in INDEX
    assert "companyLogoBackground(record.company, logo)" in INDEX
    assert "'207760', 'KOSDAQ'" in STOCKS
    assert "https://www.mrbluecorp.com/theme/basic/image/logo.png" in STOCKS
    assert "verified_raster_wordmark" in STOCKS


def test_maker_and_saved_portfolios_use_current_trends_and_companies() -> None:
    assert "hydrateMaker(selectedTrendId)" in INDEX
    assert "this.hydrateMaker();\n        this.mkWire();" in INDEX
    assert "if (!page) return;\n    page.__mk = true;" in INDEX
    assert "if (!page || page.__mk) return;" not in INDEX
    assert "#dc-root > section { position: fixed !important" in INDEX
    assert "#dc-root section { position: fixed !important" not in INDEX
    assert 'data-mk="trendselect"' in INDEX
    assert 'data-mk="trendpicker"' in INDEX
    assert "wireMakerTrendPicker(page)" in INDEX
    assert "data-mk-trend-option" in INDEX
    assert "currentByName.get(name) || seededByName.get(name)" in INDEX
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
    assert "하루 전 대비" in INDEX
    assert "이전 공개 대비" not in INDEX
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


def test_mobile_production_fills_the_real_viewport_without_a_nested_device_mockup() -> None:
    assert "@media (max-width: 600px)" in INDEX
    assert "height:100dvh !important" in INDEX
    assert 'div[style*="width:393px"][style*="height:852px"]' in INDEX
    assert "border:0 !important" in INDEX
    assert "border-radius:0 !important" in INDEX
    assert "box-shadow:none !important" in INDEX
    assert "window.matchMedia('(max-width: 600px)').matches" in INDEX
    assert "window.scrollTo({ left: 0, top: 0, behavior: 'auto' })" in INDEX
    assert "@media (max-width: 600px) { [data-screen-label] { position: fixed !important" in INDEX
    assert 'div[style*="padding:12px 24px 4px"]' in INDEX
    assert 'div[style*="width:120px"][style*="height:5px"]' in INDEX
    assert "[data-vd-stage] { height:clamp(300px, 42dvh, 370px) !important; }" in INDEX


def test_collapsed_company_folders_keep_company_names_visible() -> None:
    assert 'title="{{ f.previewNames }}"' in INDEX
    assert "previewNames: st.companies.slice(0, 3)" in INDEX
    assert "closed: !open" in INDEX


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


def test_legacy_unvalidated_archive_is_not_exposed_in_the_public_frontend() -> None:
    for token in (
        "지난 트렌드",
        "data-archive-open",
        "openArchive = async () =>",
        "ARCHIVE_URL",
        "loadArchive",
        "validatedArchive",
    ):
        assert token not in INDEX
        assert token not in DATA


def test_past_trend_research_cases_are_explorable_without_recommendation_language() -> None:
    assert 'data-past-trends-open="1"' not in INDEX
    assert "openPastTrends = () =>" in INDEX
    assert "당시 함께 살펴본 기업" in INDEX
    assert "이후 수익이나 투자 성과를 뜻하지 않습니다" in INDEX
    assert "우베 디저트" in INDEX
    assert "황치즈 스낵 확산" in INDEX
    assert "스파이더맨: 브랜드 뉴 데이" in INDEX


def test_selection_disclosure_and_portfolio_safety_rules_are_visible_and_enforced() -> None:
    home_controls = INDEX[INDEX.index('data-home-observed="1"'):INDEX.index('data-vd-stage="1"')]
    assert "선정 기준</button>" not in home_controls
    assert "openSelectionGuide" in INDEX
    assert "트렌드 선정 기준" in INDEX
    assert "정치·범죄·재난·사생활·혐오" in INDEX
    assert "사람의 최종 승인을 거친 트렌드만" in INDEX
    assert "X 대한민국 실시간 트렌드 1~30위와 Google Trending Now 대한민국 전체" in INDEX
    assert "후보 내부 정렬식" not in INDEX
    assert "우선순위 = 40 현재 위치 + 20 전시간 변화 + 20 반복 관측 + 15 최근 이력 + 5 동시 관측" not in INDEX
    assert "validatePortfolioContent(input = {})" in DATA
    assert "UNSAFE_PORTFOLIO_TEXT" in DATA
    assert "정치·범죄·혐오·수익 보장 표현은 공개할 수 없습니다." in DATA
    assert "validatePortfolioContent(input);" in DATA
    assert "portfolio_create_blocked" in INDEX
    assert "deletePortfolio(id)" in DATA


def test_selection_guide_uses_plain_language_and_human_final_approval() -> None:
    assert "사람의 최종 승인을 거친 트렌드만" in INDEX
    for token in (
        "SelectionScore",
        "35V + 25B + 20A + 10P + 10R",
        "원천 관측 순위가 아니라 홈 공개 후보의 내부 정렬식",
        "실측 원천 점수는 별도 Python 산식",
    ):
        assert token not in INDEX


def test_user_surfaces_present_one_integrated_trend_instead_of_source_brands() -> None:
    assert ">트렌드</span>" in INDEX
    assert "통합 트렌드" not in INDEX
    assert 'data-interest-card="1"' not in INDEX
    assert 'data-related-company-cta="1"' in INDEX
    assert "단계 읽는 법" not in INDEX
    assert "처음 포착된 시점과 관측이 이어진 정도를 함께 봅니다." not in INDEX
    assert "+ ' · 통합 트렌드</span>" not in INDEX
    assert "최신 트렌드 수집을 확인했습니다." in DATA
    assert "integratedTrendCopy(value)" in INDEX
    assert "const definition = this.integratedTrendCopy(item.summary || '')" in INDEX
    assert "const caption = this.integratedTrendCopy(item.raw.why_now || item.summary || '')" in INDEX
    for source_phrase in (
        "X 대한민국 실시간 트렌드 30개 + Google Trending Now 전체",
        "X와 Google 두 출처만 사용",
        "X·Google 실제 관측 순위",
        "Google 포착",
        "X 포착",
        "X·Google 원천 관측 점수",
    ):
        assert source_phrase not in INDEX
    assert "X와 Google Trends 최신 수집을 모두 확인했습니다." not in DATA
    assert "일부 원천 수집이 완료되지 않아 통합 결과를 확인하고 있습니다." in DATA
    # 원천별 값과 provenance는 UI에서 숨길 뿐 클라이언트 검증에는 남겨 둡니다.
    assert "['x', 'google_trends'].includes(point?.source)" in DATA
    assert "item.sources.every((source) => ['x', 'google_trends'].includes(source))" in DATA


def test_integrated_trend_copy_hides_source_brands_for_every_published_phrase() -> None:
    method = re.search(
        r"  integratedTrendCopy\(value\) \{\r?\n(?P<body>.*?)\r?\n  \}\r?\n\r?\n  companyName",
        INDEX,
        re.DOTALL,
    )
    assert method is not None
    samples = (
        "X와 Google 대한민국 관측에서 확인된 맥락입니다.",
        "Google Trending Now 대한민국 관측에서 확인된 맥락입니다.",
        "X 대한민국 실시간 트렌드 관측에서 확인된 맥락입니다.",
        "X 대한민국 관측에서 확인된 맥락입니다.",
        "X·Google 대한민국 관측에서 확인된 맥락입니다.",
        "X와 유튜브·브랜드 콘텐츠로 확산됐습니다.",
    )
    script = (
        "function integratedTrendCopy(value) {\n"
        + method.group("body")
        + "\n}\n"
        + f"const samples = {json.dumps(samples, ensure_ascii=False)};\n"
        + "process.stdout.write(JSON.stringify(samples.map(integratedTrendCopy)));\n"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rendered = json.loads(completed.stdout)
    assert all("X" not in value and "Google" not in value for value in rendered)
    assert all("통합" in value or "공개 콘텐츠" in value for value in rendered)


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
    assert "LIVE_RANK_RESPONSIVE_FORMULA_VERSION = 'observed-rank-response-v2'" in DATA
    assert "LIVE_RANK_RESPONSIVE_FORMULA_WEIGHTS" in DATA
    assert "LIVE_RANK_RESPONSIVE_DERIVATION" in DATA
    assert "neutral_50_for_unavailable_rank_change" in DATA
    assert "neutral_rank_change_index: 50.0" in DATA
    assert "formula_weight_sum: 1.0" in DATA
    assert "validRankResponsiveFormulaWeights(visualization.formula_weights)" in DATA
    assert "validRankResponsiveDerivation(visualization.derivation)" in DATA
    assert "sameContractValue(visualization.presentation_rank_movement, item?.rank_movement)" in DATA
    assert "validRankResponsiveSourceComponent(" in DATA
    assert "validNormalizedIndex(component.source_rank_change_index)" in DATA
    assert "validNormalizedIndex(component.public_rank_change_index)" in DATA
    assert "rankChangeBasis.length === 2" in DATA
    assert "visualization.data_mode === 'rank_responsive_display'" in DATA
    assert "visualization.display_only === true" in DATA
    assert "visualization.canonical_ranking_effect !== 'none'" in DATA
    assert "visualization.display_rank_effect !== 'display_value_only'" in DATA
    assert "visualization.market_data_affected !== false" in DATA
    assert "Object.hasOwn(visualization, '24h')" not in DATA
    assert "keywords.length === 5" in DATA
    assert "keywordTexts.every(keywordFitsPublicLabel)" in DATA
    assert "companies.length === 10" in DATA
    assert "companyIdentities.size === 10" in DATA
    assert "roles.size >= 3" in DATA
    assert "roles.size <= 4" in DATA
    assert "ontologyPathReachesCompany(company.ontology_path" in DATA
    assert "validLiveListingVerification(company.listing_verification, company, observedAt)" in DATA
    assert "validLiveMarketSnapshot(company, observedAt)" in DATA
    assert "validLiveLogo(company)" in DATA
    assert "logoPolicy.low_resolution_fallback === 'card_excluded'" in DATA
    assert "linkedKeywords.size === 5" in DATA
    assert "linkedCompanies.size === 10" in DATA
    assert "matchedKeywordsValid" in DATA
    assert "declaredCoverageValid" in DATA
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
        low_resolution_fallback: 'card_excluded', runtime_probe_for_generic_favicons: false,
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
      const sparseWindow = (hours) => ({
        status: 'insufficient_observed_history', points: [sparsePoint()],
        available_point_count: 1, available_from: observedAt, available_to: observedAt,
        expected_window_hours: hours, observed_span_hours: 0,
        observed_hour_count: 1, coverage_ratio: Math.round((1 / hours) * 10000) / 10000,
        minimum_span_hours: Math.round((hours * 0.8) * 100) / 100,
        minimum_observed_hours: Math.max(2, Math.ceil(hours * 0.2)),
        basis: 'observed_x_google_hourly_points_only', interpolation: 'none',
        missing_point_policy: 'preserve_sparse_null_no_reuse', ranking_effect: 'none',
      });
      const imageLogo = () => ({
        official_domain: 'company.example.com',
        logo_url: 'https://company.example.com/logo.svg', logo_render_mode: 'image',
        logo_asset_source: 'official_page_asset', logo_asset_host: 'company.example.com',
        logo_asset_verification: 'verified_safe_svg', logo_asset_format: 'svg',
        logo_asset_mime: 'image/svg+xml', logo_asset_width: 128, logo_asset_height: 128,
        logo_asset_sha256: 'a'.repeat(64), logo_source_page_url: 'https://company.example.com/about', logo_minimum_dimension: 64,
        logo_runtime_probe_required: false, logo_rejected_asset_url: '',
        logo_asset_quality: 'verified_vector',
        logo_quality_policy: 'avatar-sharpness-v1',
        logo_provenance: {
          source_page_url: 'https://company.example.com/about',
          asset_url: 'https://company.example.com/logo.svg', mime: 'image/svg+xml',
          width: 128, height: 128, sha256: 'a'.repeat(64), verification: 'verified_safe_svg',
        },
      });
      const listingFor = (stockCode) => ({
        status: 'verified_current', current_listed: true,
        evidence_type: 'exchange_current_security_universe',
        evidence_owner: 'KRX', evidence_url: 'https://global.krx.co.kr/contents/GLB/05/0501/0501010100/GLB0501010100.jsp',
        as_of: '2026-08-14', synthetic: false, estimated: false,
        ranking_effect: 'none', exchange: 'KRX', stock_code: stockCode,
      });
      const marketFor = () => {
        const pricePoints = Array.from({length: 30}, (_, index) => {
          const date = new Date(Date.UTC(2026, 6, 16 + index)).toISOString().slice(0, 10);
          return {date, close: 1000 + index};
        });
        const field = (sourceUrl = 'https://finance.yahoo.com/quote/TEST.KS') => ({
          provider: 'yahoo_finance', as_of: '2026-08-14', source_url: sourceUrl,
          synthetic: false, estimated: false,
        });
        return {
          status: 'observed', synthetic: false, estimated: false,
          display_only: true, ranking_effect: 'none', provider: 'pykrx+yahoo_finance',
          source: 'pykrx+yahoo_finance', as_of: '2026-08-14',
          source_url: 'https://finance.yahoo.com/quote/TEST.KS',
          price_source_url: 'https://finance.yahoo.com/quote/TEST.KS/history',
          price_points: pricePoints, price_series: pricePoints.map((row) => row.close),
          market_cap_krw: 1000000000000, market_cap: 1000000000000,
          market_cap_currency: 'KRW', native_market_cap: 1000000000000,
          fx_rate_to_krw: 1, fx_as_of: '2026-08-14', fx_provider: 'identity_krw',
          fx_source_url: 'https://global.krx.co.kr/',
          market_cap_source_url: 'https://global.krx.co.kr/',
          per: 12.3, per_status: 'observed', pbr: 1.2, roe_pct: 8.4,
          per_source_url: 'https://finance.yahoo.com/quote/TEST.KS',
          pbr_source_url: 'https://finance.yahoo.com/quote/TEST.KS',
          roe_source_url: 'https://finance.yahoo.com/quote/TEST.KS',
          field_provenance: {
            price_series: field('https://finance.yahoo.com/quote/TEST.KS/history'),
            market_cap_krw: field('https://global.krx.co.kr/'),
            per: field(), pbr: field(), roe_pct: field(),
          },
        };
      };
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
          '1w': sparseWindow(168), '1m': sparseWindow(720), '3m': sparseWindow(2160),
        },
        attention_windows: [
          ['1w', '1주'], ['1m', '1개월'], ['3m', '3개월'],
        ].map(([key, label]) => ({
          key, label, metric: 'normalized_attention_index_change',
          status: 'insufficient_observed_history', percent: null,
          basis: 'insufficient_window_span_or_coverage',
          is_absolute_mention_count: false, ranking_effect: 'none',
        })),
        context_research: {
          status: 'ready', trigger_title: `trigger-${i}`, why_now: 'documented context',
          evidence_urls: ['https://news.example.com/context'],
        },
        related_keywords: Array.from({length: 5}, (_, k) => ({text: `k${k}`})),
        companies: Array.from({length: 10}, (_, c) => {
          const stockCode = `S${i}${c}`;
          return ({
          company: `company-${i}-${c}`,
          stock_code: stockCode,
          exchange: 'KRX',
          company_role_category: roles[c % roles.length],
          company_role_label: 'verified role',
          matched_keywords: [`k${c % 5}`],
          company_description: 'listed company',
          connection_explanation: 'documented relation',
          ontology_complete: true,
          ontology_path: ['trend', 'role', `company-${i}-${c}`],
          evidence_sources: [{url: 'https://company.example.com/evidence'}],
          relation_tier: 'direct',
          listing_verification: listingFor(stockCode),
          market_snapshot: marketFor(),
          ...imageLogo(),
        }); }),
        keyword_company_links: Array.from({length: 10}, (_, k) => ({
          keyword: `k${k % 5}`, company: `company-${i}-${k}`,
          stock_code: `S${i}${k}`,
          company_role_category: roles[k % roles.length],
          company_role_label: 'verified role',
          connection_explanation: 'documented keyword relation',
          evidence_urls: ['https://company.example.com/evidence'],
        })),
        keyword_company_link_coverage: {
          policy_version: 'public-keyword-company-link-coverage-v1',
          status: 'ready', ready: true, keyword_count: 5, company_count: 10,
          valid_link_count: 10, linked_keyword_count: 5, linked_company_count: 10,
          unlinked_keywords: [], unlinked_companies: [], matched_keyword_mismatches: [],
          invalid_link_indexes: [], duplicate_pairs: [], ranking_effect: 'none',
        },
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
      const responsiveCard = completeCard(0);
      const responsiveRankMovement = {
        current_rank: 1, previous_rank: null, delta: null,
        status: 'new', label: 'NEW', basis: 'previous_published_presentation_feed',
      };
      const responsiveDerivation = {
        formula: 'mean_by_observed_source(weighted_sum(source_rank_position,rank_change,observation_persistence,presentation_position))',
        input_fields: [
          'observed_source_rank', 'observed_source_rank_change',
          'observation_persistence', 'presentation_position',
          'previous_published_presentation_position',
        ],
        missing_component_policy: 'neutral_50_for_unavailable_rank_change',
        neutral_rank_change_index: 50.0, formula_weight_sum: 1.0,
        display_only: true, canonical_ranking_effect: 'none',
        display_rank_effect: 'display_value_only', market_data_affected: false,
        canonical_series_unchanged: true,
        missing_point_policy: 'preserve_sparse_null_no_reuse',
      };
      responsiveCard.rank_movement = responsiveRankMovement;
      const responsivePoint = () => ({
        ...sparsePoint(), observation_density: 1,
        formula_version: 'observed-rank-response-v2', display_only: true,
        canonical_ranking_effect: 'none', display_rank_effect: 'display_value_only',
        market_data_affected: false,
        ranking_effect: 'none',
        source_components: {x: {
          rank: 1, snapshot_size: 30, position_index: 100,
          rank_basis: 'explicit_observed_source_rank', previous_rank: null,
          rank_change: null, rank_change_index: 50,
          source_rank_change_index: 50, public_rank_change_index: 50,
          rank_change_basis: [
            'neutral_unavailable_source_rank_change',
            'neutral_unavailable_public_rank_change',
          ],
          observation_persistence_index: 100,
          presentation_position: 1, presentation_position_index: 100,
          presentation_rank_change: null, display_index: 80,
        }},
      });
      const responsiveWindow = (hours) => ({
        ...sparseWindow(hours), points: [responsivePoint()],
        formula_version: 'observed-rank-response-v2', display_only: true,
        canonical_ranking_effect: 'none', display_rank_effect: 'display_value_only',
        market_data_affected: false,
      });
      responsiveCard.visualization_series = {
        metric: 'normalized_attention_index', canonical_series_unchanged: true,
        data_mode: 'rank_responsive_display', interpolation: 'none',
        formula_version: 'observed-rank-response-v2', display_only: true,
        formula_weights: {
          source_rank_position: 0.45, rank_change: 0.20,
          observation_persistence: 0.15, presentation_position: 0.20,
        },
        derivation: responsiveDerivation,
        presentation_position: 1, presentation_rank_movement: responsiveRankMovement,
        canonical_ranking_effect: 'none', display_rank_effect: 'display_value_only',
        market_data_affected: false, ranking_effect: 'none',
        '1w': responsiveWindow(168), '1m': responsiveWindow(720),
        '3m': responsiveWindow(2160),
      };
      if (!api.selectLiveHomeRows({presentation_feed: feedFor([responsiveCard])}).eligible) process.exit(63);
      const responsiveNotDisplayOnly = clone(responsiveCard);
      responsiveNotDisplayOnly.visualization_series.display_only = false;
      reject(feedFor([responsiveNotDisplayOnly]), 64);
      const responsiveWithoutFormula = clone(responsiveCard);
      delete responsiveWithoutFormula.visualization_series.formula_version;
      reject(feedFor([responsiveWithoutFormula]), 65);
      const responsiveWithChangedWeight = clone(responsiveCard);
      responsiveWithChangedWeight.visualization_series.formula_weights.presentation_position = 0.25;
      reject(feedFor([responsiveWithChangedWeight]), 66);
      const responsivePointNotDisplayOnly = clone(responsiveCard);
      responsivePointNotDisplayOnly.visualization_series['1w'].points[0].display_only = false;
      reject(feedFor([responsivePointNotDisplayOnly]), 67);
      const responsiveComponentMismatch = clone(responsiveCard);
      responsiveComponentMismatch.visualization_series['1w'].points[0].source_components.x.display_index = 79;
      reject(feedFor([responsiveComponentMismatch]), 68);
      const responsiveTamperCases = [
        (value) => { value.derivation.formula = 'weighted_sum'; },
        (value) => { value.derivation.input_fields.reverse(); },
        (value) => { value.derivation.missing_component_policy = 'renormalize_available_components'; },
        (value) => { value.derivation.neutral_rank_change_index = 49; },
        (value) => { value.derivation.formula_weight_sum = 0.8; },
        (value) => { value.derivation.display_only = false; },
        (value) => { value.derivation.canonical_ranking_effect = 'display'; },
        (value) => { value.derivation.display_rank_effect = 'canonical_rank'; },
        (value) => { value.derivation.market_data_affected = true; },
        (value) => { value.derivation.canonical_series_unchanged = false; },
        (value) => { value.derivation.missing_point_policy = 'carry_forward'; },
        (value) => { value.presentation_rank_movement.status = 'unchanged'; },
        (value) => { value.canonical_ranking_effect = 'display'; },
        (value) => { value.display_rank_effect = 'canonical_rank'; },
        (value) => { value.market_data_affected = true; },
        (value) => { value['1w'].formula_version = 'observed-rank-response-v1'; },
        (value) => { value['1w'].canonical_ranking_effect = 'display'; },
        (value) => { value['1w'].display_rank_effect = 'canonical_rank'; },
        (value) => { value['1w'].market_data_affected = true; },
        (value) => { value['1w'].points[0].canonical_ranking_effect = 'display'; },
        (value) => { value['1w'].points[0].display_rank_effect = 'canonical_rank'; },
        (value) => { value['1w'].points[0].market_data_affected = true; },
        (value) => { value['1w'].points[0].source_components.x.rank_change_index = null; },
        (value) => { value['1w'].points[0].source_components.x.rank = true; },
        (value) => { value['1w'].points[0].source_components.x.presentation_rank_change = false; },
        (value) => { value['1w'].points[0].source_components.x.rank_change_index = 49; },
        (value) => { value['1w'].points[0].source_components.x.source_rank_change_index = 49; },
        (value) => { value['1w'].points[0].source_components.x.public_rank_change_index = 49; },
        (value) => { value['1w'].points[0].source_components.x.rank_change_basis.pop(); },
      ];
      responsiveTamperCases.forEach((mutate, index) => {
        const tampered = clone(responsiveCard);
        mutate(tampered.visualization_series);
        reject(feedFor([tampered]), 69 + index);
      });
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
      reject(feedFor([onlyTwoRoles]), 35);
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
      const brokenLogo = completeCard(0); brokenLogo.companies[0].logo_render_mode = 'initials'; reject(feedFor([brokenLogo]), 45);
      const missingListing = completeCard(0); delete missingListing.companies[0].listing_verification; reject(feedFor([missingListing]), 52);
      const staleListing = completeCard(0); staleListing.companies[0].listing_verification.as_of = '2026-08-01'; reject(feedFor([staleListing]), 53);
      const nextDayAudit = completeCard(0); nextDayAudit.companies[0].listing_verification.as_of = '2026-08-16';
      if (!api.selectLiveHomeRows({presentation_feed: feedFor([nextDayAudit])}).eligible) process.exit(58);
      const futureListing = completeCard(0); futureListing.companies[0].listing_verification.as_of = '2026-08-17'; reject(feedFor([futureListing]), 59);
      const shortMarketSeries = completeCard(0); shortMarketSeries.companies[0].market_snapshot.price_points.pop(); reject(feedFor([shortMarketSeries]), 54);
      const syntheticMarket = completeCard(0); syntheticMarket.companies[0].market_snapshot.synthetic = true; reject(feedFor([syntheticMarket]), 55);
      const missingMarketProvenance = completeCard(0); delete missingMarketProvenance.companies[0].market_snapshot.field_provenance.roe_pct; reject(feedFor([missingMarketProvenance]), 56);
      const nonKrwMarketCap = completeCard(0); nonKrwMarketCap.companies[0].market_snapshot.market_cap_currency = 'USD'; reject(feedFor([nonKrwMarketCap]), 57);
      const perNa = completeCard(0);
      perNa.companies[0].market_snapshot.per_status = 'unavailable_loss_making';
      delete perNa.companies[0].market_snapshot.per;
      delete perNa.companies[0].market_snapshot.per_source_url;
      delete perNa.companies[0].market_snapshot.field_provenance.per;
      if (!api.selectLiveHomeRows({presentation_feed: feedFor([perNa])}).eligible) process.exit(60);
      const stalePer = completeCard(0);
      stalePer.companies[0].market_snapshot.field_provenance.per.as_of = '2026-03-19';
      reject(feedFor([stalePer]), 61);
      const syntheticSparse = completeCard(0); syntheticSparse.visualization_series['1w'].interpolation = 'linear'; reject(feedFor([syntheticSparse]), 46);
      const fakeZeroChange = completeCard(0); fakeZeroChange.attention_windows[0].percent = 0; reject(feedFor([fakeZeroChange]), 62);
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
    assert 'assets/trzip-logo.png' not in INDEX
    assert 'data-zip="logo"' in INDEX
    assert 'Trend.Zip' in INDEX
    assert 'data-zip="frame" role="button" tabindex="0"' in INDEX
    assert "frame.addEventListener('wheel'" in INDEX
    assert "frame.addEventListener('keydown'" in INDEX
    assert "['Enter', ' ', 'ArrowDown', 'PageDown']" in INDEX
    assert 'data-trend-summary-card="1"' in INDEX
    assert 'data-trend-description-toggle="1"' in INDEX
    assert 'data-trend-description-body="1"' in INDEX
    assert '트렌드 설명 보기' in INDEX
    assert 'interestPoint: null, trendDescriptionOpen: true' in INDEX
    assert 'trend: next, trendDescriptionOpen: true' in INDEX
    assert 'trend: i, trendOpen: false, trendDescriptionOpen: true' in INDEX
    assert 'trend: i, trendOpen: false, trendDescriptionOpen: false' not in INDEX
    assert 'data-trend-icon-src="{{ trendIconUrl }}"' in INDEX
    assert '{{ trendIconFallback }}</span>' in INDEX
    assert 'data-trend-summary-card="1" style="background:#FFFFFF; border-radius:0; overflow:visible;"' in INDEX
    assert INDEX.count('data-other-trends-toggle="1"') == 1
    assert INDEX.index('data-trend-description-toggle="1"') < INDEX.index('data-other-trends-toggle="1"')
    assert INDEX.index('data-other-trends-toggle="1"') < INDEX.index('data-freshness-card="1"')
    assert '이 트렌드는 무엇인가요?' not in INDEX
    assert '왜 관심을 받나요?' in INDEX
    assert 'trendDetailDefinition(trend = {})' in INDEX
    assert 'UFC는 종합격투기(MMA) 대회를 여는 글로벌 스포츠 단체입니다.' in INDEX
    assert 'trendDetailContext(trend = {})' in INDEX
    assert '이번 트렌드와 만나는 지점' in INDEX
    assert '이번 밈트폴리오와 만나는 지점' not in INDEX
    assert 'data-freshness-card="1"' in INDEX
    assert 'background:#FAFAFC; border:1px solid #E6DDF3' in INDEX
    assert 'data-freshness-explanation="1"' not in INDEX
    assert 'data-freshness-track="1"' in INDEX
    assert 'data-freshness-fill="1"' in INDEX
    assert 'data-freshness-knob="1"' in INDEX
    assert 'animateFreshnessGauge()' in INDEX
    assert "cubic-bezier(.16,.82,.24,1)" in INDEX
    assert 'data-interest-card="1"' not in INDEX
    assert 'data-related-company-cta="1"' in INDEX
    assert 'relatedCompanyPreview' in INDEX
    assert 'relatedCompanyAriaNames' in INDEX
    assert '{{ relatedCompanyNames }}' not in INDEX
    assert INDEX.index('data-related-company-cta="1"') < INDEX.index('함께 언급된 키워드')
    assert '선택한 기간의 관심 흐름을 비교해 볼 수 있습니다.' not in INDEX
    assert 'data-company-role-folder="1"' in INDEX
    assert 'data-folder-toggle="1"' in INDEX
    assert 'aria-label="{{ f.title }} {{ f.count }} 기업 목록 열기 또는 접기"' in INDEX
    assert 'data-folder-body="1"' in INDEX
    assert 'data-folder-company="1"' in INDEX
    assert "@keyframes omSheetRise" in INDEX
    assert "[data-company-dialog]{animation:omSheetRise 340ms" in INDEX
    assert "[data-folder-company]:nth-child(4){animation-delay:155ms}" in INDEX
    assert "@keyframes omListIn" in INDEX
    assert "[data-list-row]{animation:omListIn" in INDEX
    assert "[data-home-overlay]{animation:omOverlayIn" in INDEX
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
    assert 'data-trend-icon-src="{{ opt.optIconUrl }}"' in INDEX
    assert '<img src="{{ opt.optIconUrl }}"' not in INDEX
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
