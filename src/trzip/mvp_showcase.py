"""Build the isolated five-scenario MVP presentation bundle.

This is deliberately not a ranking product.  It packages five reviewed
demonstration scenarios so the frontend can demonstrate the full flow while
the live collector is still accumulating its own history.  It never reads or
writes the live SQLite ledger and never assigns a live rank or score.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .editorial_review import (
    FINAL_KEYWORD_COUNT,
    MINIMUM_VERIFIED_COMPANY_COUNT,
    _company_rows,
    _keyword_rows,
    _trend_definition,
)


SCHEMA_VERSION = "trzip-mvp-showcase-v1"
MANIFEST_SCHEMA_VERSION = "trzip-frontend-delivery-v1"
PUBLICATION_ID = "mvp-showcase-5-v1"

# This is an explicit presentation sequence, not a ranking or a manual
# override of the X + Google ranking engine.  Each name is independently
# enriched from the reviewed, evidence-backed cache in editorial_review.
SHOWCASE_SCENARIOS = (
    ("\ub9d0\ubcf5", "seasonal_food_ritual"),
    ("\uc9c0\uc2a4\ud0c0", "gaming_digital"),
    ("\ud2f0\ube59", "screen_content"),
    ("\ubd88\uaf43\ucd95\uc81c", "place_experience"),
    ("\uc544\uc774\ud3f0", "product_brand"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _scenario(topic: str, category: str, order: int, generated_at: str) -> dict[str, Any]:
    seed = {"category": category, "keywords": [], "companies": []}
    keywords = _keyword_rows(seed, cache_key=topic)
    companies = _company_rows(seed, cache_key=topic, verified_at=generated_at)
    if len(keywords) != FINAL_KEYWORD_COUNT:
        raise ValueError(f"showcase keyword contract failed: {topic}")
    if len(companies) < MINIMUM_VERIFIED_COMPANY_COUNT:
        raise ValueError(f"showcase company contract failed: {topic}")

    enriched = {
        "display_name": topic,
        "category": category,
        "keywords": keywords,
        "companies": companies,
    }
    return {
        "event_key": topic,
        "display_name": topic,
        "presentation_order": order,
        "ranking_kind": "mvp_showcase_order",
        "ranking_effect": "none",
        "category": category,
        "trend_definition": _trend_definition(enriched, topic),
        "observation_summary": "60\uc77c \uc7ac\ud604 \uc2dc\uc5f0 \ub370\uc774\ud130\uc640 \uac80\ud1a0\ub41c \uad00\ub828\uc5b4\u00b7\uae30\uc5c5 \uc628\ud1a8\ub85c\uc9c0\ub97c \uacb0\ud569\ud55c MVP \uc2dc\ub098\ub9ac\uc624\uc785\ub2c8\ub2e4.",
        "related_keywords": keywords,
        "company_candidates": companies,
        "company_display_policy": {
            "minimum_company_count": MINIMUM_VERIFIED_COMPANY_COUNT,
            "investment_recommendation": False,
            "ranking_effect": "none",
        },
        "display_contract_status": "complete",
        "source_evidence_urls": [row["evidence_url"] for row in companies],
        "data_lineage": {
            "observation_mode": "mvp_showcase",
            "ranking_effect": "none",
            "enrichment_source": "reviewed_term_specific_cache",
        },
    }


def build_mvp_showcase(root: Path, *, generated_at: datetime | None = None) -> dict[str, Any]:
    """Write the manifest-last, non-live showcase bundle and return its manifest."""

    root = Path(root).resolve()
    now = (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    stage = root.parent / f".{root.name}.stage"
    if stage.exists():
        shutil.rmtree(stage)
    if root.exists():
        shutil.rmtree(root)

    trends = [
        _scenario(topic, category, order, now)
        for order, (topic, category) in enumerate(SHOWCASE_SCENARIOS, start=1)
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "mvp_showcase",
        "live_eligible": False,
        "ranking_effect": "none",
        "publication_id": PUBLICATION_ID,
        "generated_at": now,
        "observed_at": None,
        "demo_label": "MVP \uc644\uc131 \uc2dc\ub098\ub9ac\uc624 \uc2dc\uc5f0 (\uc2e4\uc2dc\uac04 \uc21c\uc704 \uc544\ub2d8)",
        "trends": trends,
    }
    payload_path = stage / "latest" / "showcase.json"
    _write_json(payload_path, payload)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mode": "mvp_showcase",
        "live_eligible": False,
        "ranking_effect": "none",
        "publication_id": PUBLICATION_ID,
        "generated_at": now,
        "observed_at": None,
        "demo_label": payload["demo_label"],
        "bundle": {
            "showcase": {
                "path": "showcase.json",
                "sha256": _sha256(payload_path),
                "trend_count": len(trends),
            }
        },
    }
    _write_json(stage / "latest" / "manifest.json", manifest)
    stage.replace(root)
    validate_mvp_showcase(root)
    return manifest


def validate_mvp_showcase(root: Path) -> dict[str, Any]:
    """Fail closed if the presentation bundle can be mistaken for live data."""

    root = Path(root).resolve()
    manifest = json.loads((root / "latest" / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("mode") != "mvp_showcase" or manifest.get("live_eligible") is not False:
        raise ValueError("showcase must be explicitly non-live")
    if manifest.get("ranking_effect") != "none":
        raise ValueError("showcase cannot affect a ranking")
    entry = manifest.get("bundle", {}).get("showcase", {})
    payload_path = root / "latest" / str(entry.get("path") or "")
    if not payload_path.is_file() or _sha256(payload_path) != entry.get("sha256"):
        raise ValueError("showcase payload hash mismatch")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if payload.get("mode") != "mvp_showcase" or payload.get("ranking_effect") != "none":
        raise ValueError("showcase payload has invalid mode")
    trends = payload.get("trends") or []
    if len(trends) != len(SHOWCASE_SCENARIOS):
        raise ValueError("showcase scenario count mismatch")
    for order, trend in enumerate(trends, start=1):
        if trend.get("presentation_order") != order or trend.get("ranking_kind") != "mvp_showcase_order":
            raise ValueError("showcase ordering contract failed")
        if len(trend.get("related_keywords") or []) != FINAL_KEYWORD_COUNT:
            raise ValueError("showcase keyword count mismatch")
        if len(trend.get("company_candidates") or []) < MINIMUM_VERIFIED_COMPANY_COUNT:
            raise ValueError("showcase company count mismatch")
    return manifest
