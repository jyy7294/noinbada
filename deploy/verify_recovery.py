"""Run on the isolated TR ZIP host; verifies an actual API restart and backup restore."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

from trzip.runtime.core import home, now_iso, atomic_json, decode


def get(path):
    with urlopen("http://127.0.0.1:8448"+path,timeout=4) as response:
        return json.load(response)


before=get("/api/trends")
started=time.monotonic()
subprocess.run(["systemctl","kill","--kill-whom=main","--signal=SIGKILL","trzip-api.service"],check=True)
after=None
for _ in range(25):
    try:
        after=get("/api/trends")
        break
    except Exception:
        time.sleep(1)
assert after is not None,"API did not recover"
elapsed=round(time.monotonic()-started,2)
assert after["publication_id"]==before["publication_id"],"Edition changed unexpectedly during restart"
report=json.loads(subprocess.check_output(["runuser","-u","trzip","--preserve-environment","--",sys.executable,"-m","trzip.runtime","maintain"],text=True))
backup=home()/"backups"/report["backup"]
restored=home()/"backups"/"restore-verification.sqlite3"
with sqlite3.connect(backup) as source, sqlite3.connect(restored) as dest:
    source.backup(dest)
    assert dest.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    current=dest.execute("SELECT value FROM settings WHERE key='current_publication'").fetchone()[0]
    edition=decode(dest.execute("SELECT payload FROM publications WHERE id=?",(current,)).fetchone()[0])
    assert len(edition["items"])>0
restored.unlink()
evidence={"verified_at":now_iso(),"api_restart_seconds":elapsed,"publication_preserved":True,"backup_restore_integrity":"ok",
          "restored_items":len(edition["items"]),"disk_reserve_bytes":report["free_bytes"]}
atomic_json(home()/"recovery-evidence.json",evidence)
print(json.dumps(evidence,ensure_ascii=False))
