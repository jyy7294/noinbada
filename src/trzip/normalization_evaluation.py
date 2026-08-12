from __future__ import annotations

import json
from pathlib import Path

from .event_resolution import resolve_event


DEFAULT_HOLDOUT = Path(__file__).resolve().parents[2] / "config" / "normalization_holdout.json"


def evaluate_holdout(path: Path | None = None) -> dict:
    source = path or DEFAULT_HOLDOUT
    payload = json.loads(source.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    errors = []
    name_correct = category_correct = ambiguity_correct = 0
    ambiguity_total = dangerous_false_links = 0
    for case in cases:
        actual = resolve_event(case["input"], {"x", "google_trends"})
        expected_context = case.get("context_status")
        checks = {
            "display_name": actual["canonical"] == case.get("display_name"),
            "category": actual["category"] == case.get("category"),
            "context_status": actual["context_status"] == expected_context,
        }
        name_correct += checks["display_name"]
        category_correct += checks["category"]
        if expected_context in {"ambiguous_person", "needs_context"}:
            ambiguity_total += 1
            ambiguity_correct += checks["context_status"]
            dangerous_false_links += actual["context_status"] == "resolved_reference"
        if not all(checks.values()):
            errors.append({
                "input": case["input"],
                "expected": {key: case.get(key) for key in ("display_name", "category", "context_status")},
                "actual": {
                    "display_name": actual["canonical"],
                    "category": actual["category"],
                    "context_status": actual["context_status"],
                },
                "failed_checks": [key for key, passed in checks.items() if not passed],
            })
    total = len(cases)
    name_accuracy = round(name_correct / total, 4) if total else None
    category_accuracy = round(category_correct / total, 4) if total else None
    ambiguity_hold_accuracy = round(ambiguity_correct / ambiguity_total, 4) if ambiguity_total else None
    targets_met = bool(
        total and name_accuracy >= 0.85 and category_accuracy >= 0.90 and dangerous_false_links == 0
    )
    return {
        "schema_version": "trzip-normalization-evaluation-v1",
        "holdout_schema_version": payload.get("schema_version"),
        "holdout_frozen_at": payload.get("frozen_at"),
        "scope": payload.get("scope"),
        "evaluated_count": total,
        "name_accuracy": name_accuracy,
        "category_accuracy": category_accuracy,
        "ambiguity_hold_accuracy": ambiguity_hold_accuracy,
        "dangerous_false_links": dangerous_false_links,
        "targets": {"name_accuracy": 0.85, "category_accuracy": 0.90, "dangerous_false_links": 0},
        "targets_met": targets_met,
        "errors": errors,
        "warning": "2026-08-12 실제 관측 24건의 고정 평가 결과이며 미관측 신규 사건 전체에 대한 일반화 성능은 아닙니다.",
    }


def write_holdout_report(output: Path, path: Path | None = None) -> dict:
    report = evaluate_holdout(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
