"""Export all non-political/non-crime/non-disaster topics for one source."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path


POLICY_VERSION = "single-source-rolling-v2-exclude-politics-crime-disaster-only"
EXCLUSION_RULES = (
    ("politics", ("대통령", "국회", "선거", "정당", "민주당", "국민의힘", "이재명", "윤석열", "탄핵", "검찰", "특검", "지지율", "장관", "여야", "정치")),
    ("crime_or_personal_harm", ("사망", "살인", "살해", "폭행", "체포", "구속", "범죄", "실종", "피해자", "성폭력", "마약", "음주운전", "괴롭힘", "협박", "강간")),
    ("disaster_or_accident", ("재난", "태풍", "폭우", "홍수", "지진", "산불", "화재", "붕괴", "침수", "폭설", "사고", "참사")),
)


def parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--observed-at must include a timezone")
    return parsed.astimezone(UTC)


def excluded_reason(topic: str) -> str | None:
    normalized = topic.casefold()
    for reason, markers in EXCLUSION_RULES:
        if any(marker.casefold() in normalized for marker in markers):
            return reason
    return None


def score_topic(observations: list[tuple[datetime, int, int]], snapshot_count: int, end: datetime) -> dict:
    seen_at = {row[0] for row in observations}
    persistence = len(seen_at) / snapshot_count if snapshot_count else 0.0
    rank_strength = sum((depth + 1 - rank) / depth for _, rank, depth in observations) / len(observations)
    last_seen = max(seen_at)
    age_hours = max(0.0, (end - last_seen).total_seconds() / 3600)
    recency = 0.5 ** (age_hours / 12.0)
    return {
        "rolling_observed_score": round(100 * ((0.55 * persistence) + (0.35 * rank_strength) + (0.10 * recency)), 4),
        "observed_snapshots": len(seen_at),
        "persistence": round(persistence, 6),
        "average_rank_strength": round(rank_strength, 6),
        "recency": round(recency, 6),
        "best_source_rank": min(rank for _, rank, _ in observations),
        "latest_source_rank": next((rank for at, rank, _ in observations if at == end), None),
        "last_seen_at": last_seen.isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source", choices=("x", "google_trends"), required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    end = parse_at(args.observed_at)
    start = end - timedelta(hours=max(1, args.hours))
    minimum_rows = 30 if args.source == "x" else 100
    exact_rows = args.source == "x"

    with sqlite3.connect(args.database) as connection:
        snapshots = connection.execute(
            """SELECT observed_at, COUNT(*) FROM hourly_observations
               WHERE source=? AND provenance='observed' AND observed_at BETWEEN ? AND ?
               GROUP BY observed_at ORDER BY observed_at""",
            (args.source, start.isoformat(), end.isoformat()),
        ).fetchall()
        valid = [(at, int(count)) for at, count in snapshots if count == minimum_rows] if exact_rows else [(at, int(count)) for at, count in snapshots if count >= minimum_rows]
        placeholders = ",".join("?" for _ in valid) or "NULL"
        rows = connection.execute(
            f"""SELECT observed_at, topic, source_rank FROM hourly_observations
                WHERE source=? AND provenance='observed' AND observed_at IN ({placeholders})
                ORDER BY observed_at, source_rank, topic""",
            (args.source, *(at for at, _ in valid)),
        ).fetchall() if valid else []

    depth_by_time = dict(valid)
    topics: dict[str, dict] = {}
    for observed_at, topic, rank in rows:
        display = " ".join(str(topic).split())
        key = display.casefold()
        entry = topics.setdefault(key, {"topic": display, "observations": []})
        entry["observations"].append((parse_at(observed_at), int(rank), depth_by_time[observed_at]))

    included: list[dict] = []
    excluded: list[dict] = []
    for entry in topics.values():
        row = {"topic": entry["topic"], **score_topic(entry["observations"], len(valid), end)}
        reason = excluded_reason(entry["topic"])
        if reason:
            row["excluded_reason"] = reason
            excluded.append(row)
        else:
            included.append(row)
    included.sort(key=lambda row: (-row["rolling_observed_score"], row["topic"].casefold()))
    excluded.sort(key=lambda row: (-row["rolling_observed_score"], row["topic"].casefold()))
    for number, row in enumerate(included, start=1):
        row["rolling_observed_rank"] = number

    payload = {
        "schema_version": "trzip-single-source-rolling-report-v1",
        "policy_version": POLICY_VERSION,
        "source": args.source,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "hours": args.hours},
        "valid_snapshot_rule": "exactly_30_observed_rows" if exact_rows else "at_least_100_observed_rows",
        "valid_snapshots": len(valid),
        "observed_rows": len(rows),
        "score_formula": "55% repeated observation + 35% average normalized source rank + 10% recency",
        "included_count": len(included),
        "excluded_count": len(excluded),
        "included_topics": included,
        "excluded_topics": excluded,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.source} 최근 {args.hours}시간 누적 관측 순위",
        "",
        f"- 기준 시각: {end.isoformat()}",
        f"- 정상 스냅샷: {len(valid)}회, 관측 행: {len(rows)}개",
        f"- 포함: {len(included)}개 / 제외: {len(excluded)}개 (정치·범죄·재난만 제외)",
        "- 점수: 반복 관측 55% + 평균 정규화 원천순위 35% + 최신성 10%",
        "",
        "## 포함 전체", "", "|누적 순위|키워드|점수|관측 횟수|최고 원천순위|최신 원천순위|마지막 관측|", "|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in included:
        lines.append(f"|{row['rolling_observed_rank']}|{row['topic']}|{row['rolling_observed_score']:.2f}|{row['observed_snapshots']}|{row['best_source_rank']}|{row['latest_source_rank'] or '-'}|{row['last_seen_at']}|")
    lines.extend(["", "## 제외 전체", "", "|키워드|제외 이유|점수|", "|---|---|---:|"])
    for row in excluded:
        lines.append(f"|{row['topic']}|{row['excluded_reason']}|{row['rolling_observed_score']:.2f}|")
    args.markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"source": args.source, "included": len(included), "excluded": len(excluded), "valid_snapshots": len(valid)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
