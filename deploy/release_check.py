"""Read-only release gate. Never changes production pointers or Vercel aliases."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
from trzip.runtime.core import home, now_iso, ROOT
from trzip.runtime.api import reader
from trzip.runtime.pipeline import status

with reader() as db:
    result=status(db)
    integrity=db.execute("PRAGMA quick_check").fetchone()[0]
evidence_path=home()/"recovery-evidence.json"
evidence=json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
qa_path=home()/"browser-qa.json"
qa=json.loads(qa_path.read_text()) if qa_path.exists() else {}
web_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'web').iterdir() if p.name in {'index.html','app.css','app.js','icon.svg'}}
code_paths=list((ROOT/'src/trzip/runtime').glob('*.py'))+[ROOT/'src/trzip/google_web_collector.py',ROOT/'src/trzip/company_logo_assets.py']
runtime_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
timers=all(subprocess.run(["systemctl","is-active","--quiet",name]).returncode==0 for name in ("trzip-api.service","trzip-collect.timer","trzip-enrich.timer","trzip-maintain.timer"))
checks={"continuous_operation":result["release_gate"]["automatic_checks_pass"],"integrity":integrity=="ok",
        "api_recovery":0<evidence.get("api_restart_seconds",99999)<1200,"backup_restore":evidence.get("backup_restore_integrity")=="ok",
        "collector_recovery":0<evidence.get("collector_recovery_seconds",99999)<1200 and evidence.get("prior_observations_preserved") is True,
        "desktop_qa":qa.get("desktop") is True,"mobile_qa":qa.get("mobile") is True,
        "verified_web_unchanged":web_hashes==qa.get("web_hashes"),"verified_runtime_unchanged":runtime_hashes==qa.get("runtime_hashes"),
        "timers":timers,"disk_reserve":shutil.disk_usage(home()).free>=5*1024**3}
print(json.dumps({"checked_at":now_iso(),"ready_for_review":all(checks.values()),"checks":checks,"operation":result},ensure_ascii=False))
raise SystemExit(0 if all(checks.values()) else 2)
