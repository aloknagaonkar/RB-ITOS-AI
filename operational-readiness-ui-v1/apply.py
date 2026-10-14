"""Install UI-only readiness monitoring into an existing repository, with backups."""
import shutil,sys,subprocess,datetime
from pathlib import Path
root=Path.cwd();bundle=Path(__file__).resolve().parent;changes={}
def change(rel,old,new):
 p=root/rel;s=changes.get(p,p.read_text())
 if old not in s:raise SystemExit('Expected source marker missing: '+rel+'; no changes made')
 changes[p]=s.replace(old,new,1)
api='backend/market_lab/api.py';worker='backend/market_lab/live_shadow_worker_v1.py';app='frontend/src/App.tsx';hist='backend/market_lab/hilega_milega_historical_replay_v1.py'
if 'operational_readiness_v1' in (root/api).read_text():raise SystemExit('Readiness already installed; no changes made')
change(api,'from contextlib import asynccontextmanager','from .operational_readiness_v1 import router as operational_readiness_router\nfrom contextlib import asynccontextmanager')
change(api,'    app.include_router(hilega_pcr_context_router)','    app.include_router(operational_readiness_router)\n    app.include_router(hilega_pcr_context_router)')
change(app,"import { lazy, Suspense, useEffect, useRef, useState } from 'react'","import OperationalReadiness from './operationalReadiness'\nimport { lazy, Suspense, useEffect, useRef, useState } from 'react'")
p=root/app;changes[p]=changes[p].replace('<main>',"<main><OperationalReadiness expanded={tab==='Data health'}/>")
change(worker,'_component_retry_after = {}','_component_retry_after = {}\n_component_errors = {}')
change(worker,'            _component_retry_after.pop(name, None)','            _component_retry_after.pop(name, None)\n            _component_errors.pop(name, None)')
change(worker,'            outcomes[name] = type(exc).__name__','''            outcomes[name] = type(exc).__name__
            # Keep only whitelisted candle-validation messages; provider strings may contain secrets.
            import re
            message = str(exc)
            safe = isinstance(exc, ValueError) and len(message) < 500 and re.fullmatch(r"[A-Za-z0-9 :,;._\\-]+", message) and any(word in message.lower() for word in ("warmup", "candle", "missing 1m"))
            _component_errors[name] = {"first_seen": _component_errors.get(name, {}).get("first_seen", now.isoformat()), "last_failure": now.isoformat(), "error_type": type(exc).__name__, "message": message if safe else type(exc).__name__}''')
change(worker,'"components": outcomes}),','"components": outcomes, "component_errors": _component_errors}),')
old='        aggregate_exact_5m(repaired, session_date, require_full_session=True)'
new='''        try:
            aggregate_exact_5m(repaired, session_date, require_full_session=True)
        except ValueError as exc:
            raise ValueError(f"Warmup {session_date}: {exc}") from exc'''
change(hist,old,new)
# Scripts are scoped lifecycle hooks; monitoring itself runs independently.
for rel in ('scripts/start.sh','scripts/restart.sh'):
 p=root/rel;s=p.read_text();changes[p]=s+'\n# UI-only operational readiness\nbash "$ROOT/scripts/start_operational_readiness.sh"\n'
p=root/'scripts/stop.sh';changes[p]=p.read_text()+'\n# Stop independent readiness monitor\nbash "$ROOT/scripts/stop_operational_readiness.sh"\n'
p=root/'scripts/status.sh';changes[p]=p.read_text()+'''\nif [ -f data/operational-readiness.pid ] && kill -0 "$(cat data/operational-readiness.pid)" 2>/dev/null; then
    echo "readiness-monitor: RUNNING (UI-only)"
else
    echo "readiness-monitor: STOPPED"
fi
'''
stamp=datetime.datetime.now().strftime('%Y%m%dT%H%M%S');backup=root/'data/backups'/('operational-readiness-'+stamp)
for p in changes:
 target=backup/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
for p,s in changes.items():p.write_text(s)
for p in (bundle/'files').rglob('*'):
 if p.is_file():
  target=root/p.relative_to(bundle/'files');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
  if target.suffix=='.sh':target.chmod(0o755)
subprocess.run([sys.executable,'-m','compileall','-q',str(root/'backend/market_lab/operational_readiness_v1.py'),str(root/worker),str(root/hist)],check=True)
print('Installed. Backup:',backup)
print('Next: run tests; build frontend; restart to load worker error details and API route.')
