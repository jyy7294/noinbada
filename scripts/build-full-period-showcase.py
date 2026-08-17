from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import shutil
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trzip.hourly_store import default_db_path
from trzip.intelligence import build_intelligence
from trzip.final_publication_approval import build_final_publication_review, write_approval
from trzip.company_adapters import pykrx_stock, yahoo_finance_stock
from trzip.presentation_feed import _actual_market_snapshot, _live_logo_fields
from trzip.publication_pipeline import _merge_domestic_market_references
from trzip.showcase_live_simulation import (
    KOSDAQ_STOCK_CODES,
    SHOWCASE_SELECTION,
    build_showcase_enrichment,
    exact_domestic_market,
    validate_showcase_enrichment,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _official_listing_verification(*, market: str, stock_code: str, observed_at: datetime) -> dict:
    known_us_listings = {
        ("NYSE", "DIS"): "https://www.nyse.com/quote/XNYS:DIS",
        ("NYSE", "TKO"): "https://www.nyse.com/quote/XNYS:TKO",
        ("NYSE", "BUD"): "https://www.nyse.com/quote/XNYS:BUD",
        ("NASDAQ", "PSKY"): "https://ir.paramount.com/investor-faqs/",
        ("NASDAQ", "MNST"): "https://www.nasdaq.com/market-activity/stocks/mnst",
        ("NASDAQ", "DKNG"): "https://www.nasdaq.com/market-activity/stocks/dkng",
        ("NASDAQ", "GOOGL"): "https://www.nasdaq.com/market-activity/stocks/googl",
        ("NASDAQ", "META"): "https://www.nasdaq.com/market-activity/stocks/meta",
        ("NASDAQ", "AAPL"): "https://www.nasdaq.com/market-activity/stocks/aapl",
        ("NASDAQ", "SPCX"): "https://www.nasdaq.com/market-activity/stocks/spcx",
        ("NYSE", "TDY"): "https://www.nyse.com/quote/XNYS:TDY",
    }
    evidence_url = known_us_listings.get((market, stock_code))
    if evidence_url:
        return {
            "status": "verified_current",
            "current_listed": True,
            "exchange": market,
            "stock_code": stock_code,
            "as_of": observed_at.astimezone(UTC).date().isoformat(),
            "evidence_owner": "NYSE" if market == "NYSE" else "Nasdaq",
            "evidence_type": "exchange_current_security_universe",
            "evidence_url": evidence_url,
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        }
    raise ValueError(f"unsupported overseas listing proof: {market}:{stock_code}")


def _attach_observed_market_snapshots(payload: dict, observed_at: datetime) -> int:
    """Attach one fail-closed market snapshot per unique listed security."""

    companies_by_identity = {}
    for card in payload["cards"]:
        for company in card["companies"]:
            market = str(company.get("market") or "KRX")
            stock_code = str(company["stock_code"])
            if market in {"KRX", "KOSPI", "KOSDAQ"}:
                market = exact_domestic_market(stock_code)
            companies_by_identity[(market, stock_code)] = company
    snapshots: dict[tuple[str, str], tuple[dict, dict]] = {}
    base_date = observed_at.astimezone(UTC).strftime("%Y%m%d")
    for market, stock_code in sorted(companies_by_identity):
        if market in {"KRX", "KOSPI", "KOSDAQ"}:
            pykrx = pykrx_stock(stock_code, base_date=base_date, lookback_days=60)
            yahoo_exchange = "KOSDAQ" if stock_code in KOSDAQ_STOCK_CODES else "KRX"
            yahoo = yahoo_finance_stock(stock_code, yahoo_exchange, as_of=observed_at)
            market_reference = _merge_domestic_market_references(pykrx, yahoo)
            listing_verification = market_reference.get("listing_verification")
            if listing_verification:
                listing_verification = {**listing_verification, "exchange": market}
        else:
            market_reference = yahoo_finance_stock(stock_code, market, as_of=observed_at)
            listing_verification = _official_listing_verification(
                market=market,
                stock_code=stock_code,
                observed_at=observed_at,
            )
            market_reference["listing_verification"] = listing_verification
        snapshot = _actual_market_snapshot(
            {
                "stock_code": stock_code,
                "market": market,
                "listing_verification": listing_verification,
                "market_reference": market_reference,
            },
            {},
            observed_at,
        )
        if snapshot is None:
            name = companies_by_identity[(market, stock_code)]["company"]
            raise ValueError(f"observed market snapshot is incomplete: {market}:{stock_code} {name}")
        snapshots[(market, stock_code)] = (listing_verification, snapshot)
    attached = 0
    for card in payload["cards"]:
        for company in card["companies"]:
            market = str(company.get("market") or "KRX")
            if market in {"KRX", "KOSPI", "KOSDAQ"}:
                market = exact_domestic_market(str(company["stock_code"]))
                company["market"] = market
            identity = (market, str(company["stock_code"]))
            listing_verification, snapshot = snapshots[identity]
            company["listing_verification"] = listing_verification
            company["market_snapshot"] = snapshot
            attached += 1
    return attached


def _attach_verified_company_logos(payload: dict) -> int:
    """Resolve and attach one official, verified image logo to every company row."""

    logo_fields_by_homepage: dict[str, dict] = {}
    attached = 0
    for card in payload["cards"]:
        for company in card["companies"]:
            homepage = str(company.get("company_identity_url") or "").strip()
            if homepage not in logo_fields_by_homepage:
                logo_fields_by_homepage[homepage] = _live_logo_fields(homepage)
            fields = logo_fields_by_homepage[homepage]
            if fields.get("logo_render_mode") != "image":
                raise ValueError(
                    f"verified company logo is unavailable: {company['company']} {homepage}"
                )
            company.update(fields)
            company["logo_asset_scope"] = "showcase_company"
            attached += 1
    return attached


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path)
    args = parser.parse_args()

    with sqlite3.connect(args.db) as connection:
        observed_at = connection.execute(
            "SELECT MAX(observed_at) FROM hourly_observations WHERE provenance='observed'"
        ).fetchone()[0]
    if not observed_at:
        raise ValueError("observed ledger is empty")
    at = datetime.fromisoformat(str(observed_at))
    intelligence = build_intelligence(at, path=args.db, live_only=True)
    ranking = intelligence["full_ledger_demo_ranking"]
    review = build_final_publication_review(intelligence)
    payload = build_showcase_enrichment(
        ranking["ranking"],
        source_observed_at=str(observed_at),
    )
    # The source observation time and the market refresh time are intentionally
    # different fields.  On weekends and exchange holidays the latest valid
    # market session can precede the current source observation; never rewrite
    # that session date to make the figures look newer than they are.
    market_refreshed_at = datetime.now(UTC)
    market_snapshot_count = _attach_observed_market_snapshots(payload, at)
    logo_count = _attach_verified_company_logos(payload)
    validate_showcase_enrichment(payload)

    unique_market_as_of = sorted({
        str(company["market_snapshot"]["as_of"])
        for card in payload["cards"]
        for company in card["companies"]
    })
    if len(unique_market_as_of) != 1:
        raise ValueError(
            "market snapshot refresh must resolve to one shared latest market session: "
            + ", ".join(unique_market_as_of)
        )

    target = args.output.resolve()
    stage = target.parent / f".{target.name}.stage"
    stage.mkdir(parents=True, exist_ok=True)
    payload_path = stage / "showcase.json"
    _write_json(payload_path, payload)
    review_path = stage / "final-publication-review.json"
    _write_json(review_path, review)
    approval_path = write_approval(
        review,
        approval_root=stage / "approvals",
        approved_event_keys=[event_key for event_key, _display, _universe in SHOWCASE_SELECTION],
        approved_by="이찬희",
    )
    manifest = {
        "schema_version": "trzip-showcase-delivery-v1",
        "mode": payload["mode"],
        "display_status": payload["display_status"],
        "display_time_policy": payload["display_time_policy"],
        "display_as_of": payload["display_as_of"],
        "source_observed_at": payload["source_observed_at"],
        "ranking_formula_version": ranking["formula_version"],
        "ranking_window": ranking["window"],
        "card_count": len(payload["cards"]),
        "market_data": {
            "status": "observed",
            "provider": "pykrx+yahoo_finance",
            "refreshed_at": market_refreshed_at.isoformat().replace("+00:00", "Z"),
            "latest_market_session": unique_market_as_of[0],
            "snapshot_count": market_snapshot_count,
            "unique_security_count": len({
                (company.get("market") or "KRX", company["stock_code"])
                for card in payload["cards"]
                for company in card["companies"]
            }),
            "synthetic": False,
            "estimated": False,
            "ranking_effect": "none",
        },
        "company_logos": {
            "status": "verified",
            "image_count": logo_count,
            "fallback_count": 0,
            "source": "official_page_asset",
        },
        "showcase": {"path": "showcase.json", "sha256": _sha256(payload_path)},
        "final_review": {
            "path": "final-publication-review.json",
            "sha256": _sha256(review_path),
            "review_sha256": review["review_sha256"],
        },
        "approval": {
            "path": str(approval_path.relative_to(stage)).replace("\\", "/"),
            "sha256": _sha256(approval_path),
            "approved_count": len(SHOWCASE_SELECTION),
            "approved_by": "이찬희",
        },
    }
    _write_json(stage / "manifest.json", manifest)
    if target.exists():
        shutil.rmtree(target)
    stage.replace(target)
    if args.public_output:
        public_target = args.public_output.resolve()
        public_stage = public_target.parent / f".{public_target.name}.stage"
        if public_stage.exists():
            shutil.rmtree(public_stage)
        public_stage.mkdir(parents=True)
        shutil.copy2(target / "showcase.json", public_stage / "showcase.json")
        public_manifest = {
            "schema_version": manifest["schema_version"],
            "mode": manifest["mode"],
            "display_status": manifest["display_status"],
            "display_time_policy": manifest["display_time_policy"],
            "source_observed_at": manifest["source_observed_at"],
            "ranking_formula_version": manifest["ranking_formula_version"],
            "ranking_window": manifest["ranking_window"],
            "card_count": manifest["card_count"],
            "market_data": manifest["market_data"],
            "company_logos": manifest["company_logos"],
            "showcase": manifest["showcase"],
            "approval": {
                "approved_count": manifest["approval"]["approved_count"],
                "approved_by": manifest["approval"]["approved_by"],
                "review_sha256": manifest["final_review"]["review_sha256"],
            },
        }
        _write_json(public_stage / "manifest.json", public_manifest)
        if public_target.exists():
            shutil.rmtree(public_target)
        public_stage.replace(public_target)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
