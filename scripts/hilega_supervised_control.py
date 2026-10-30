from urllib.error import HTTPError, URLError
"""Control the three preparation services through the existing shell entry points."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROLES=('api','worker','production-source-worker')

def need(ok,reason):
    if not ok: raise RuntimeError(reason)

def service_mode(root,home):
    paths=[home/'.config/systemd/user'/('hilega-'+r+'.service') for r in ROLES]
    present=[p.exists() or p.is_symlink() for p in paths]
    if not any(present):
        need(not (home/'hilega-persistent-supervision-stage-v1/MIGRATION_APPROVED.json').exists(),
             'SUPERVISION_CONFIG_MISSING_NO_LEGACY_FALLBACK')
        return False
    need(all(present) and all(p.is_file() and not p.is_symlink() for p in paths),
         'PARTIAL_OR_INVALID_SUPERVISION_NO_LEGACY_FALLBACK')
    return True

def command(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=35)
    need(p.returncode==0,'SYSTEMD_COMMAND_FAILED')
    return p.stdout.strip()

def unit_status(role):
    text=command(['systemctl','--user','show','hilega-'+role+'.service',
                  '-p','LoadState','-p','ActiveState','-p','MainPID'])
    return dict(line.split('=',1) for line in text.splitlines() if '=' in line)

def no_detached_processes(rows,units):
    for row in rows:
        need(int(units[row['role']]['MainPID'])==row['pid'],
             'DETACHED_PROCESS_PRESENT_USE_GUARDED_MIGRATION')


def api_health_available(probe):
    """Retry connection failures only; preserve HTTP and safety failures."""
    try:
        probe()
        return True
    except HTTPError:
        raise
    except URLError:
        return False

def main(action,root=None,home=None):
    root=(root or Path(__file__).resolve().parents[1]).resolve()
    home=home or Path.home()
    enabled=service_mode(root,home)
    if action=='mode': return 0 if enabled else 10
    need(enabled,'SUPERVISION_NOT_INSTALLED')
    sys.path.insert(0,str(root/'hilega-production-application-deployment'))
    from managed_processes import inspect
    units={r:unit_status(r) for r in ROLES}
    rows=inspect(root)['active_processes']
    no_detached_processes(rows,units)
    if action=='status':
        print(json.dumps(dict(supervision='SYSTEMD_USER',services=units,
                              managed_processes=rows,production_execution_enabled=False),indent=2))
        return 0 if all(v.get('ActiveState')=='active' for v in units.values()) else 1
    need(all(v.get('LoadState')=='loaded' for v in units.values()),
         'SERVICE_DEFINITIONS_NOT_READY')
    path=root/'hilega-supervision-migration-tools-v1/migrate-persistent-supervision.py'
    spec=importlib.util.spec_from_file_location('supervision_guards',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    stage=home/'hilega-persistent-supervision-stage-v1'
    runner=m.load_runner(stage)
    runner.paused(root)  # Never automatically arm or pause a trading controller.
    if action=='start':
        config_path=stage/'config-private.json'
        config=json.loads(runner.regular(config_path))
        permit=json.loads(runner.regular(stage/'MIGRATION_APPROVED.json'))
        need(permit['config_sha256']==m.sha(config_path),'CONFIG_CHANGED')
        need(permit['runner_sha256']==m.sha(stage/'runner.py'),'RUNNER_CHANGED')
        need(m.sha(root/'.env')==config['env_sha256'],'ENV_CHANGED_REVIEW_REQUIRED')
        for role in ('worker','api','production-source-worker'):
            command(['systemctl','--user','start','hilega-'+role+'.service'])
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            units={r:unit_status(r) for r in ROLES}
            rows=inspect(root)['active_processes']
            no_detached_processes(rows,units)
            if len(rows)==3 and all(v.get('ActiveState')=='active' for v in units.values()):
                if not api_health_available(m.api_health):
                    time.sleep(1)
                    continue
                runner.paused(root)
                print('application: three supervised preparation services running; controller PAUSED')
                print('source freshness requires a separate readiness check')
                return 0
            time.sleep(1)
        raise RuntimeError('SUPERVISED_START_VERIFICATION_INCOMPLETE')
    need(action=='stop','ACTION_INVALID')
    for role in ('production-source-worker','worker','api'):
        command(['systemctl','--user','stop','hilega-'+role+'.service'])
    need(not inspect(root)['active_processes'],'APPLICATION_PROCESS_REMAINS')
    print('application: three supervised services stopped')
    return 0

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('mode','start','stop','status'))
    try: raise SystemExit(main(p.parse_args().action))
    except Exception as exc:
        print(json.dumps(dict(status='SUPERVISED_CONTROL_BLOCKED',
              reason=str(exc) if type(exc) is RuntimeError else type(exc).__name__,
              automatic_retry=False)))
        raise SystemExit(78)
