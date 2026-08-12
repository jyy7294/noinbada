import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_deployed_design_shows_one_active_screen_at_a_time():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "[data-screen-label] { display:none !important; }" in html
    assert "data-z-active-screen" in html
    assert "jump(requestedIndex);" in html
    assert "new URLSearchParams(window.location.search).get('screen')" in html


def test_meme_portfolio_mock_is_labeled_but_live_company_market_is_bound():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    adapter = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")

    assert "두바이초콜릿 이름값 3종 담았다" in html
    assert "+18.2%" in html
    assert "밈트폴리오 예시 화면 · 수익률/좋아요는 목업" in html
    assert "captureMemeMock" in html
    assert "restoreMemeMock" in html
    assert "company.market_reference" in html
    assert "summary.daily_change_pct" in html
    assert "LIVE_DATA_BASE" in adapter
    assert "INTELLIGENCE_URL" in adapter
    assert "STATUS_URL" in adapter
    assert "METADATA_URL" in adapter
    assert "mode !== 'live'" in adapter
    assert "DEFAULT_LIVE_BASE" not in adapter
    assert "TRZIP_DATA_BASE" not in adapter
    assert "dataBase=/live" not in html


def test_live_series_and_hidden_developer_navigation_are_bound():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "data-z-series-bars" in html
    assert "renderTrendSeries" in html
    assert "#zp-nav { display:none !important; }" in html
    assert "relation_display_type" in html
    assert "team_review_label" in html


def test_review_required_trends_are_visibly_labelled_without_company_claims():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    adapter = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")

    assert "homeContextStatus: item.home_context_status || 'resolved'" in adapter
    assert "reviewRequired: item.home_context_status === 'review_required'" in adapter
    assert "t.reviewRequired ? ' · 검토 필요' : ''" in html
    assert "맥락 검토 필요 · 기업 연결 보류" in html


def test_company_ineligible_detail_clears_mock_company_and_purchase_cta():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    adapter = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")

    assert "data-z-portfolio-cta" in html
    assert "setCompanyAvailability" in html
    assert "if (!companies.length)" in html
    assert "data-z-company-hold" in html
    assert "기업 연결 보류 · " in html
    assert "portfolioCta.style.display = hasCompanies ? 'flex' : 'none'" in html
    assert "buy.style.display = 'none'" in html
    assert "sheet.setAttribute('aria-hidden', 'true')" in html
    assert "if (!dim || !sheet || !company || !company.company) return;" in html
    assert "companies: companyEligible && Array.isArray(item.companies) ? item.companies : []" in adapter
    assert 'data-z-sh-name="1" style="font-weight:900; font-size:19px; color:#6B554A; letter-spacing:-0.01em;">신라교역' not in html


def test_live_bundle_exposes_fresh_partial_stale_status_without_snapshot_override():
    adapter = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")

    assert "Promise.all" in adapter
    assert "validatedBundle" in adapter
    assert "snapshotMismatch" in adapter
    assert "FRESH_FOR_MINUTES" in adapter
    assert "STALE_AFTER_MINUTES" in adapter
    assert "fromCache || !observedAt" in adapter
    assert "statusResponse" in adapter
    assert "unavailableSources" in adapter
    assert "publicationIdentity" in adapter
    assert "validationMode: 'publication_id'" in adapter
    assert "validationMode: 'legacy_observed_at'" in adapter
    assert "new URLSearchParams" not in adapter


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for adapter contract test")
def test_frontend_rejects_mixed_publications_and_keeps_legacy_observed_bundle_compatible(tmp_path):
    adapter = ROOT / "frontend" / "trendzip-data.js"
    module = tmp_path / "trendzip-data.mjs"
    module.write_text(adapter.read_text(encoding="utf-8"), encoding="utf-8")
    module_url = module.resolve().as_uri()
    script = f"""
      const {{ validatedBundle }} = await import({json.dumps(module_url)});
      const observed = '2026-08-12T03:00:00+00:00';
      const generated = '2026-08-12T03:00:05+00:00';
      const intelligence = {{
        mode: 'live', publication_id: 'pub-one', generated_at: generated,
        window: {{ to: observed }}, unified_ranking: []
      }};
      const metadata = {{
        mode: 'live', publication_id: 'pub-one', generated_at: generated,
        observed_at: observed
      }};
      const status = {{
        mode: 'live', publication_id: 'pub-one', generated_at: generated,
        observed_at: observed
      }};
      const accepted = validatedBundle(intelligence, metadata, status).publication;
      let mismatch = null;
      try {{
        validatedBundle(intelligence, metadata, {{ ...status, publication_id: 'pub-two' }});
      }} catch (error) {{ mismatch = String(error.message || error); }}
      const legacy = validatedBundle(
        {{ mode: 'live', window: {{ to: observed }}, unified_ranking: [] }},
        {{ mode: 'live', generated_at: generated, observed_at: observed }},
        {{ mode: 'live', generated_at: generated, observed_at: observed }}
      ).publication;
      console.log(JSON.stringify({{ accepted, mismatch, legacy }}));
    """
    completed = subprocess.run(
        [shutil.which("node"), "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert result["accepted"] == {
        "id": "pub-one",
        "generatedAt": "2026-08-12T03:00:05.000Z",
        "validationMode": "publication_id",
        "legacy": False,
    }
    assert "publication_id" in result["mismatch"]
    assert result["legacy"]["validationMode"] == "legacy_observed_at"
    assert result["legacy"]["legacy"] is True


def test_empty_or_failed_live_data_clears_mock_trend_and_disables_dial():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "공개 가능한 트렌드가 없어요" in html
    assert "목업으로 대신 표시하지 않습니다" in html
    assert "clearLiveScreens" in html
    assert "clearPortfolioDraft" in html
    assert "[data-z-dial][data-z-active-trend=\"1\"]" in html
    assert "unzip.disabled = state !== 'ready'" in html
    assert "if (this.data.error) states.push('실시간 연결 실패')" in html


def test_portfolio_persists_actual_keyword_and_company_selection_and_reopens_it():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    adapter = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")

    assert "selectedKeywords" in html
    assert "selectedCompanies" in html
    assert "companies: self.portfolioDraft.selectedCompanies" in html
    assert "keywords: self.portfolioDraft.selectedKeywords" in html
    assert "window.prompt('직접 추가할 키워드를 입력해 주세요.')" in html
    assert "openSavedPortfolio" in html
    assert "data-z-saved-company-list" in html
    assert "export function getPortfolio" in adapter
    assert "var kwPool" not in html
    assert "var pool" not in html


def test_remote_company_text_is_not_inserted_as_html():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "openCompanySheet" in html
    assert "role2.textContent" in html
    assert "why.textContent" in html
    assert "impact.textContent" in html
    assert ".innerHTML = c[" not in html
    assert "company.reason, priceText" not in html
