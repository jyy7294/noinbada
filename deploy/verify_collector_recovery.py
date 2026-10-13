"""Controlled failure of an isolated collector unit; no synthetic observations."""
import json
import subprocess
import sys
import time
from trzip.runtime.api import reader
from trzip.runtime.core import home, now_iso, atomic_json

def state():
    with reader() as db:
        run=db.execute('SELECT id,status FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        observations=db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        return dict(run),observations

before,count=state()
unit='trzip-collection-recovery'
properties=['--property=User=trzip','--property=Group=trzip','--property=WorkingDirectory=/srv/services/trzip/current',
            '--property=EnvironmentFile=/srv/services/trzip/runtime.env','--property=MemoryMax=768M','--property=CPUQuota=75%',
            '--property=RuntimeMaxSec=240','--property=LogNamespace=trzip']
command=[sys.executable,'-m','trzip.runtime','collect','--force']
subprocess.run(['systemd-run','--collect','--unit='+unit,*properties,*command],check=True)
started=False
for _ in range(1000):
    latest,_=state()
    if latest['id']>before['id'] and latest['status']=='running':
        started=True
        break
    time.sleep(0.1)
if not started:
    subprocess.run(['systemctl','stop',unit+'.service'],check=False)
    raise AssertionError('Did not observe a running collection')
subprocess.run(['systemctl','kill','--kill-whom=all','--signal=SIGKILL',unit+'.service'],check=True)
begin=time.monotonic()
subprocess.run(['systemd-run','--wait','--collect','--unit='+unit+'-retry',*properties,*command],check=True,timeout=300)
latest,after_count=state()
assert latest['status']=='ok',latest
assert after_count>=count,'Previous observations were lost'
path=home()/'recovery-evidence.json'
evidence=json.loads(path.read_text()) if path.exists() else {}
evidence.update({'collector_recovery_seconds':round(time.monotonic()-begin,2),'collector_recovery_at':now_iso(),
                 'prior_observations_preserved':True,'observation_count_after':after_count})
atomic_json(path,evidence)
print(json.dumps(evidence,ensure_ascii=False))
