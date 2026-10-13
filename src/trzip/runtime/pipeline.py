"""One serialized writer; immutable editions; observations never invented on failure."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import gzip
import json
import os
from pathlib import Path
import shutil

from . import collectors
from .core import atomic_json, atomic_bytes, connect, encode, home, now_iso, parse_time, writer_lock

FRESH_MINUTES = {"google": 30, "youtube": 120}


def lane(title: str) -> str:
    # A conservative routing rule, not an inferred sentiment or recommendation.
    markers = ("살인", "사망", "사고", "성폭", "성범죄", "태풍", "지진", "전쟁", "대통령", "탄핵", "총선", "구속", "피해자", "날씨", "심정지", "추돌", "살해", "피습", "실종")
    return "issue" if any(word in title for word in markers) else "general"


def latest_receipts(db):
    return db.execute("SELECT r.* FROM receipts r WHERE r.status='ok' AND r.id=(SELECT MAX(s.id) FROM receipts s WHERE s.source=r.source AND s.status='ok')").fetchall()


def history(db, event: str, source: str, frame: str, at: str) -> list[dict]:
    rows = db.execute("SELECT observed_at,position FROM observations WHERE event_id=? AND source=? AND sampling_frame=? AND observed_at>=? ORDER BY observed_at DESC LIMIT 144",
                      (event, source, frame, (parse_time(at)-timedelta(hours=24)).isoformat())).fetchall()
    return [{"observed_at": r["observed_at"], "position": r["position"]} for r in reversed(rows)]


def build_publication(db, at: str) -> dict:
    sources, events = [], {}
    for receipt in latest_receipts(db):
        age = (parse_time(at) - parse_time(receipt["observed_at"])).total_seconds() / 60
        fresh = 0 <= age <= FRESH_MINUTES[receipt["source"]]
        meta = json.loads(receipt["detail"])
        sources.append({**meta, "source": receipt["source"], "observed_at": receipt["observed_at"],
                        "row_count": receipt["row_count"], "fresh": fresh})
        for observation in db.execute("SELECT * FROM observations WHERE receipt_id=? ORDER BY position", (receipt["id"],)):
            row = json.loads(observation["payload"])
            item = events.setdefault(row["event_id"], {**row, "sources": [], "score": 0, "fresh": False,
                                                       "lane": lane(row["title"]), "companies": [], "company_status": "pending"})
            item["score"] += 1 / (60 + row["position"]) if fresh else 0
            item["fresh"] = item["fresh"] or fresh
            item["sources"].append({"source": receipt["source"], "position": row["position"],
                                    "observed_at": receipt["observed_at"], "sampling_frame": receipt["sampling_frame"],
                                    "rank_basis": meta.get("rank_basis", row["rank_basis"]),
                                    "source_url": row["source_url"], "fresh": fresh})
            item["history"] = history(db, row["event_id"], receipt["source"], receipt["sampling_frame"], at)
            item["change"] = None
            if len(item["history"]) >= 3:
                previous = item["history"][-2]["position"]
                item["change"] = previous - row["position"]
            enriched = db.execute("SELECT updated_at,payload FROM enrichment WHERE event_id=?", (row["event_id"],)).fetchone()
            if enriched and 0 <= (parse_time(at)-parse_time(enriched["updated_at"])).total_seconds() <= 86400:
                item.update(json.loads(enriched["payload"]))
            if item["lane"] == "issue":
                item["companies"] = []
                item["company_status"] = "issue_excluded"
    ordered = sorted(events.values(), key=lambda x: (not x["fresh"], -x["score"], x["event_id"]))
    for index, item in enumerate(ordered, 1):
        item["rank"] = index
        item["score"] = round(item["score"], 8)
        item["image"] = item.get("image") or {"kind": "text", "url": f'/api/media/card/{item["event_id"]}.svg', "attribution": "TR ZIP 자동 텍스트 카드"}
    observed = max((s["observed_at"] for s in sources), default=None)
    return {"schema_version": 1, "published_at": at, "observed_at": observed,
            "mode": "candidate", "ranking_method": "출처별 순위의 역순위 합산 RRF(k=60). RSS는 피드 노출 순서이며 검색량 순위가 아닙니다.",
            "sources": sources, "items": ordered,
            "limitations": ["전체 인터넷의 실시간 순위가 아닙니다.", "관련 기업은 관계와 현재 상장 여부를 확인한 경우에만 표시합니다.", "X는 유료 API가 필요해 수집하지 않습니다."]}


def publish(db, root: Path, at: str | None = None) -> dict:
    payload = build_publication(db, at or now_iso())
    # Content addressing pins list, detail and status to the same edition.
    edition = hashlib.sha256(encode(payload).encode()).hexdigest()[:24]
    payload["publication_id"] = edition
    path = root / "public" / "editions" / (edition + ".json.gz")
    compressed = gzip.compress(encode(payload).encode(),mtime=0)
    atomic_bytes(path, compressed)
    with db:
        db.execute("INSERT OR IGNORE INTO publications VALUES (?,?,?,?)", (edition, payload["published_at"], payload["observed_at"] or "", compressed))
        db.execute("INSERT OR REPLACE INTO settings VALUES ('current_publication',?)", (edition,))
    # Recoverable mirror; API pointer is the committed SQLite setting above.
    atomic_json(root / "public" / "manifest.json", {"publication_id": edition, "url": "editions/"+edition+".json.gz", "observed_at": payload["observed_at"]})
    return payload


def run(root: Path | None = None, *, at: str | None = None, adapters=None, force=False) -> dict:
    root = root or home()
    injected_time = at is not None
    at = at or now_iso()
    minute = parse_time(at).replace(second=0, microsecond=0)
    slot = minute.replace(minute=minute.minute//10*10).isoformat()
    adapters = adapters if adapters is not None else {"google": lambda: collectors.collect_google(root), **({"youtube": collectors.youtube} if os.environ.get("YOUTUBE_API_KEY") else {})}
    with writer_lock(root), connect(root) as db:
        if shutil.disk_usage(root).free < 5*1024**3:
            raise RuntimeError("disk_reserve_below_5_GiB")
        first = db.execute("SELECT MIN(started_at) FROM runs").fetchone()[0] or at
        db.execute("INSERT OR IGNORE INTO settings VALUES ('first_started_at',?)",(first,))
        # Holding the exclusive lock proves no previous writer is still active.
        db.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running'",(now_iso(),))
        db.commit()
        previous = db.execute("SELECT * FROM runs WHERE slot=?", (slot,)).fetchone()
        if previous and previous["status"] == "ok" and not force:
            return {"status": "already_collected", "slot": slot}
        if previous:
            # Retry a failed/interrupted slot without erasing earlier receipts.
            if previous["status"]=="running":
                db.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE id=?",(now_iso(),previous["id"]))
            slot += "/retry/" + now_iso()
        run_id = db.execute("INSERT INTO runs(slot,started_at,status) VALUES (?,?,'running')", (slot, at)).lastrowid
        db.commit()
        failures = {}
        for source, adapter in adapters.items():
            try:
                rows, meta = adapter()
                if source not in FRESH_MINUTES or not rows or len({r["event_id"] for r in rows}) != len(rows):
                    raise ValueError("invalid or duplicate observations")
                if any(not r["title"].strip() or not isinstance(r["position"], int) or r["position"] < 1 for r in rows):
                    raise ValueError("invalid position or title")
                # Timestamp is actual fetch completion, except explicit deterministic test runs.
                stamp = at if injected_time else now_iso()
                with db:
                    rid = db.execute("INSERT INTO receipts(run_id,source,sampling_frame,observed_at,status,row_count,detail) VALUES (?,?,?,?,'ok',?,?)", (run_id, source, meta["sampling_frame"], stamp, len(rows), encode(meta))).lastrowid
                    for row in rows:
                        db.execute("INSERT INTO observations(receipt_id,event_id,source,sampling_frame,observed_at,position,payload) VALUES (?,?,?,?,?,?,?)", (rid,row["event_id"],source,meta["sampling_frame"],stamp,row["position"],encode(row)))
                        db.execute("INSERT INTO jobs(event_id,title,next_at,updated_at) VALUES (?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET title=excluded.title, status=CASE WHEN jobs.updated_at<? THEN 'pending' ELSE jobs.status END", (row["event_id"],row["title"],stamp,stamp,(parse_time(stamp)-timedelta(hours=12)).isoformat()))
            except Exception as exc:
                # Never log URLs, credentials or raw upstream response bodies.
                code = getattr(exc, "code", type(exc).__name__)
                failures[source] = code
                with db:
                    db.execute("INSERT INTO receipts(run_id,source,sampling_frame,observed_at,status,row_count,detail) VALUES (?,?,'unavailable',?,'failed',0,?)", (run_id,source,at,encode({"reason": code})))
        status = "ok" if not failures else "partial" if len(failures)<len(adapters) else "failed"
        db.execute("UPDATE runs SET finished_at=?,status=?,detail=? WHERE id=?", (now_iso(),status,encode(failures),run_id))
        db.commit()
        result = publish(db, root, at if injected_time else now_iso())
        return {"status": status, "publication_id": result["publication_id"], "items": len(result["items"]), "failures": failures}


def status(db, at: str | None = None) -> dict:
    at = at or now_iso()
    first = db.execute("SELECT value FROM settings WHERE key='first_started_at'").fetchone()
    start = first[0] if first else db.execute("SELECT MIN(started_at) FROM runs").fetchone()[0]
    elapsed = max(0, (parse_time(at)-parse_time(start)).total_seconds()/3600) if start else 0
    since = (parse_time(at)-timedelta(hours=72)).isoformat()
    receipts = db.execute("SELECT * FROM receipts WHERE observed_at>=? ORDER BY id", (since,)).fetchall()
    google = [r for r in receipts if r["source"] == "google"]
    successes = sum(r["status"] == "ok" for r in google)
    expected = max(1, min(433, int(elapsed*6)+1))
    success_slots = {parse_time(r["observed_at"]).replace(minute=parse_time(r["observed_at"]).minute//10*10,second=0,microsecond=0) for r in google if r["status"] == "ok"}
    availability = min(1, len(success_slots)/expected)
    latest = []
    for source in FRESH_MINUTES:
        attempts = [r for r in receipts if r["source"] == source]
        ok = next((r for r in reversed(attempts) if r["status"] == "ok"), None)
        age = (parse_time(at)-parse_time(ok["observed_at"])).total_seconds()/60 if ok else None
        latest.append({"source":source,"status": "fresh" if age is not None and 0<=age<=FRESH_MINUTES[source] else "stale" if ok else "not_configured" if not attempts else "failed",
                       "last_success_at":ok["observed_at"] if ok else None,"last_attempt_status":attempts[-1]["status"] if attempts else None})
    return {"checked_at":at,"started_at":start,"observation_hours":round(elapsed,2),"sources":latest,
            "google_successes":successes,"google_attempts":len(google),"scheduled_slot_coverage":round(availability,4),
            "release_gate":{"minimum_hours":72,"minimum_slot_coverage":0.95,"automatic_checks_pass":elapsed>=72 and availability>=0.95 and latest[0]["status"]=="fresh",
                            "requires":["72시간 관찰", "예정된 수집 구간의 95% 이상 성공", "중단 후 2주기 이내 복구 시험", "모바일·PC 실제 사용자 흐름 확인", "서버 여유 공간 5 GiB 이상"]}}
