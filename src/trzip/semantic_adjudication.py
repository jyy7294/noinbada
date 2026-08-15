"""Bounded LLM semantic adjudication for ambiguous live trend candidates.

Python remains responsible for source ingestion, rank arithmetic, safety hard
blocks and publication validation.  This module gives an LLM authority where
rules are weakest: deciding whether observed expressions describe one concrete,
consumer-relevant phenomenon and assigning its public category.  Every decision
is evidence-bounded, cached and auditable; it cannot alter X/Google ranks or
invent URLs, companies or keywords.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


PUBLIC_CATEGORIES = {
    "food", "content", "sports", "lifestyle", "culture", "consumer",
    "technology", "market",
}
DECISIONS = {"approve", "review", "exclude"}
MAX_REVIEWS_PER_HOUR = 12
MIN_APPROVAL_CONFIDENCE = 0.65


def _iso(at: datetime) -> str:
    if at.tzinfo is None:
        raise ValueError("semantic review timestamp must be timezone-aware")
    return at.astimezone(UTC).isoformat()


def _public_urls(values: object) -> list[str]:
    return list(dict.fromkeys(
        str(value).strip() for value in (values or [])
        if str(value).strip().startswith(("https://", "http://"))
    ))


def _fingerprint(item: dict) -> str:
    context = item.get("context_research") or {}
    payload = {
        "event_key": item.get("event_key"),
        "display_name": item.get("display_name"),
        "raw_terms": sorted(str(value) for value in item.get("raw_terms") or []),
        "context_urls": _public_urls(context.get("evidence_urls")),
        "context_title": context.get("trigger_title"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def initialize_semantic_cache(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS semantic_adjudications (
                 event_key TEXT NOT NULL,
                 fingerprint TEXT NOT NULL,
                 reviewed_at TEXT NOT NULL,
                 decision_json TEXT NOT NULL,
                 PRIMARY KEY(event_key, fingerprint)
               )"""
        )


def _cached(path: Path, item: dict) -> dict | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """SELECT decision_json FROM semantic_adjudications
               WHERE event_key=? AND fingerprint=?""",
            (str(item.get("event_key") or ""), _fingerprint(item)),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _store(path: Path, item: dict, at: datetime, decision: dict) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT INTO semantic_adjudications(event_key,fingerprint,reviewed_at,decision_json)
               VALUES (?,?,?,?)
               ON CONFLICT(event_key,fingerprint) DO UPDATE SET
                 reviewed_at=excluded.reviewed_at, decision_json=excluded.decision_json""",
            (
                str(item.get("event_key") or ""), _fingerprint(item), _iso(at),
                json.dumps(decision, ensure_ascii=False, sort_keys=True),
            ),
        )


def semantic_review_prompt(item: dict) -> dict:
    """Create the compact, evidence-limited input supplied to an LLM."""

    context = item.get("context_research") or {}
    return {
        "event_key": str(item.get("event_key") or ""),
        "observed_expression": str(item.get("display_name") or ""),
        "observed_terms": list(dict.fromkeys(
            str(value).strip() for value in item.get("raw_terms") or [] if str(value).strip()
        ))[:12],
        "source_presence": sorted((item.get("latest_source_ranks") or {}).keys()),
        "news_context": {
            "trigger_title": str(context.get("trigger_title") or ""),
            "why_now": str(context.get("why_now") or ""),
            "evidence_urls": _public_urls(context.get("evidence_urls")),
        },
        "allowed_categories": sorted(PUBLIC_CATEGORIES),
        "task": (
            "Decide whether this is a concrete, consumer, content, event, technology, "
            "market or participation trend. Use only supplied evidence. Return JSON with "
            "decision (approve/review/exclude), broad_category, confidence (0..1), "
            "reason, evidence_urls. Do not claim causality, invent a URL, alter ranks, "
            "recommend an investment, or infer facts absent from the evidence."
        ),
    }


def validate_decision(raw: object, item: dict) -> dict | None:
    """Reject malformed or ungrounded model output before it gains any authority."""

    if not isinstance(raw, dict):
        return None
    decision = str(raw.get("decision") or "").strip().casefold()
    category = str(raw.get("broad_category") or "").strip().casefold()
    reason = str(raw.get("reason") or "").strip()
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        return None
    context_urls = set(_public_urls((item.get("context_research") or {}).get("evidence_urls")))
    evidence_urls = _public_urls(raw.get("evidence_urls"))
    if (
        decision not in DECISIONS
        or category not in PUBLIC_CATEGORIES
        or not 0.0 <= confidence <= 1.0
        or len(reason) < 20
        or not evidence_urls
        or not set(evidence_urls).issubset(context_urls)
    ):
        return None
    return {
        "decision": decision,
        "broad_category": category,
        "confidence": round(confidence, 4),
        "reason": reason[:600],
        "evidence_urls": evidence_urls,
        "authority": "llm_semantic_adjudication_v1",
    }


def apply_decision(item: dict, decision: dict) -> None:
    """Apply bounded semantic authority without touching source measurements."""

    item["semantic_adjudication"] = decision
    item["semantic_adjudication_status"] = "reviewed"
    if item.get("lane") == "issue":
        item["semantic_adjudication_effect"] = "hard_issue_lane_preserved"
        return
    if decision["decision"] == "approve" and decision["confidence"] >= MIN_APPROVAL_CONFIDENCE:
        item["lane"] = "main"
        item["broad_category"] = decision["broad_category"]
        item["category"] = decision["broad_category"]
        item["category_basis"] = "llm_evidence_bounded_semantic_adjudication"
        item["context_status"] = "semantically_resolved"
        item["semantic_adjudication_effect"] = "promoted_or_confirmed_main"
    elif decision["decision"] in {"review", "exclude"}:
        item["lane"] = "review"
        item["semantic_adjudication_effect"] = "held_for_review"
    else:
        item["semantic_adjudication_effect"] = "below_approval_confidence"


def _default_transport(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_model(prompt: dict, transport: Callable[[str, dict, dict[str, str]], dict]) -> object:
    """Call a configured OpenAI-compatible endpoint; disabled is a valid state."""

    url = os.getenv("TRZIP_SEMANTIC_LLM_URL", "").strip()
    api_key = os.getenv("TRZIP_SEMANTIC_LLM_API_KEY", "").strip()
    model = os.getenv("TRZIP_SEMANTIC_LLM_MODEL", "").strip()
    if not (url and api_key and model):
        return None
    response = transport(url, {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return only valid JSON. Follow the evidence boundary exactly."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def run_semantic_adjudication(
    intelligence: dict,
    *,
    path: Path,
    at: datetime,
    transport: Callable[[str, dict, dict[str, str]], dict] | None = None,
    allow_model_calls: bool = True,
) -> dict:
    """Use cached decisions first, then review only a bounded ambiguous set."""

    initialize_semantic_cache(path)
    configured = all(os.getenv(name, "").strip() for name in (
        "TRZIP_SEMANTIC_LLM_URL", "TRZIP_SEMANTIC_LLM_API_KEY", "TRZIP_SEMANTIC_LLM_MODEL"
    ))
    limit = max(0, min(MAX_REVIEWS_PER_HOUR, int(os.getenv("TRZIP_SEMANTIC_LLM_LIMIT", "12"))))
    reviewed = cached = rejected = 0
    pending: list[dict] = []
    for item in intelligence.get("unified_ranking", []):
        # Safety lanes are never presented to the model as promotable work.
        # Marking this explicitly makes the audit record distinguish a hard
        # policy exclusion from a missing provider context.
        if item.get("lane") == "issue":
            item["semantic_adjudication_status"] = "hard_issue_not_reviewed"
            item["semantic_adjudication_effect"] = "hard_issue_lane_preserved"
            continue
        cached_decision = _cached(path, item)
        if cached_decision:
            apply_decision(item, cached_decision)
            cached += 1
            continue
        if (
            item.get("lane") != "issue"
            and (item.get("context_research") or {}).get("status") == "ready"
            and (item.get("latest_source_ranks") or {})
        ):
            pending.append(item)
        else:
            item["semantic_adjudication_status"] = "not_eligible"
    pending.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("event_key") or "")))
    if configured and allow_model_calls:
        call = transport or _default_transport
        for item in pending[:limit]:
            try:
                decision = validate_decision(_request_model(semantic_review_prompt(item), call), item)
            except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError):
                decision = None
            if decision is None:
                item["semantic_adjudication_status"] = "model_output_rejected"
                rejected += 1
                continue
            _store(path, item, at, decision)
            apply_decision(item, decision)
            reviewed += 1
    else:
        for item in pending:
            item["semantic_adjudication_status"] = (
                "deferred_to_enrichment_checkpoint"
                if configured and not allow_model_calls
                else "disabled_not_configured"
            )
    intelligence["semantic_adjudication_run"] = {
        "policy": "llm_semantic_adjudication_v1",
        "configured": configured,
        "model_calls_allowed_this_run": allow_model_calls,
        "status": (
            "disabled_missing_config" if not configured
            else "deferred_to_enrichment_checkpoint" if not allow_model_calls
            else "completed" if reviewed or cached
            else "attempted_no_accepted_decision" if pending
            else "skipped_no_eligible_candidates"
        ),
        "reviewed": reviewed,
        "cached": cached,
        "rejected": rejected,
        "candidate_limit": limit,
        "authority": ["lane_for_non_issue_candidates", "broad_category", "semantic_context"],
        "prohibited": ["x_google_rank", "canonical_score", "evidence_url_invention", "company_or_keyword_padding"],
    }
    return intelligence
