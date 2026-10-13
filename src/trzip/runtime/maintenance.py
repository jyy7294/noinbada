from datetime import timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
from .core import connect, home, now_iso, parse_time, writer_lock


def maintain(root: Path | None = None):
    root = root or home()
    with writer_lock(root), connect(root) as db:
        before = (parse_time(now_iso())-timedelta(days=14)).isoformat()
        # Archive provenance before removing it from the hot database.
        archive = root/"archive"
        archive.mkdir(exist_ok=True)
        for table, column in (("observations","observed_at"),("receipts","observed_at"),("runs","started_at")):
            rows = db.execute(f"SELECT * FROM {table} WHERE {column}<?",(before,))
            first = rows.fetchone()
            if first:
                path = archive/(now_iso()[:10]+"-"+table+"-"+str(first["id"])+".jsonl.gz")
                temp = path.with_suffix(".tmp")
                with gzip.open(temp,"wt",encoding="utf-8") as stream:
                    stream.write(json.dumps(dict(first),ensure_ascii=False)+"\n")
                    for row in rows:
                        stream.write(json.dumps(dict(row),ensure_ascii=False)+"\n")
                with temp.open("r+b") as stream:
                    os.fsync(stream.fileno())
                temp.replace(path)
                path.with_suffix(path.suffix+".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest(),encoding="ascii")
        # A bounded rolling observation ledger; publication history remains 7 days.
        db.execute("DELETE FROM observations WHERE observed_at<?",(before,))
        db.execute("DELETE FROM receipts WHERE observed_at<?",(before,))
        db.execute("DELETE FROM runs WHERE started_at<?",(before,))
        db.execute("DELETE FROM enrichment WHERE updated_at<?",(before,))
        db.execute("DELETE FROM jobs WHERE updated_at<?",(before,))
        current = db.execute("SELECT value FROM settings WHERE key='current_publication'").fetchone()
        cutoff = (parse_time(now_iso())-timedelta(days=7)).isoformat()
        old = db.execute("SELECT id FROM publications WHERE published_at<? AND id!=?",(cutoff,current[0] if current else "")).fetchall()
        for row in old:
            (root/"public"/"editions"/(row[0]+".json")).unlink(missing_ok=True)
            (root/"public"/"editions"/(row[0]+".json.gz")).unlink(missing_ok=True)
            db.execute("DELETE FROM publications WHERE id=?",(row[0],))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        media = sorted((root/"media").glob("*.png"),key=lambda p:p.stat().st_mtime,reverse=True)
        used = 0
        for path in media:
            used += path.stat().st_size
            if used>128*1024**2:
                path.unlink()
                path.with_suffix(".json").unlink(missing_ok=True)
        backup = root/"backups"
        backup.mkdir(exist_ok=True)
        import sqlite3
        target = backup/(now_iso()[:10]+".sqlite3")
        with sqlite3.connect(target) as dest:
            db.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise RuntimeError("backup_integrity_failed")
        for path in sorted(backup.glob("*.sqlite3"))[:-3]:
            path.unlink()
        free = shutil.disk_usage(root).free
        return {"retained_days":14,"free_bytes":free,"space_ok":free>=5*1024**3,"backup":target.name}
