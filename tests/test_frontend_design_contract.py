from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployed_design_shows_one_active_screen_at_a_time():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "[data-screen-label] { display:none !important; }" in html
    assert "data-z-active-screen" in html
    assert "jump(1);" in html


def test_meme_portfolio_mock_is_preserved_but_live_company_market_is_bound():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    adapter = (ROOT / "frontend" / "trendzip-data.js").read_text(encoding="utf-8")

    assert "두바이초콜릿 이름값 3종 담았다" in html
    assert "+18.2%" in html
    assert "company.market_reference" in html
    assert "marketSummary.daily_change_pct" in html
    assert "DEFAULT_LIVE_BASE" in adapter
    assert "mode !== 'live'" in adapter
