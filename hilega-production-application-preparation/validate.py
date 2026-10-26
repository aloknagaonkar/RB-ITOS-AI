"""Run staged application integration + selected regressions on the user's VM."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();stage=args.stage.resolve()
    marker=stage/'APPLICATION_PREPARATION_STAGED.json'
    manifest=json.loads((HERE/'manifest.json').read_text())
    if not marker.is_file() or json.loads(marker.read_text()).get('files')!=manifest['files']:
        raise SystemExit('EXACT_STAGED_APPLICATION_REQUIRED')
    for name,wanted in manifest['files'].items():
        if hashlib.sha256((stage/name).read_bytes()).hexdigest()!=wanted:
            raise SystemExit('STAGED_FILE_CHANGED')
    if args.report.exists():raise SystemExit('FRESH_VALIDATION_REPORT_REQUIRED')
    env=dict(os.environ)
    # Strip runtime configuration/credentials in the test subprocess only.
    for key in list(env):
        if key.startswith(('HILEGA_','UPSTOX_')):env.pop(key,None)
    env['PYTHONPATH']=str(stage/'backend')+os.pathsep+str(stage)
    env['HILEGA_PRODUCTION_EXECUTION_ROUTE']='SIMULATOR'
    env['HILEGA_PRODUCTION_WORKSPACE_MODE']='DISABLED'
    env['HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED']='0'
    env['HILEGA_PRODUCTION_BROKER_OBSERVE']='0'
    env['HILEGA_PRODUCTION_SIM_DB']=str(stage/'validation-private/workspace.sqlite')
    tests=['tests/test_hilega_application_preparation_v1.py',
           'tests/test_hilega_production_control_foundation_v1.py',
           'tests/test_hilega_production_bridge_health_v1.py',
           'tests/test_hilega_production_workspace_v1.py',
           'tests/test_hilega_production_simulator_bridge_v1.py']
    result=subprocess.run([sys.executable,'-m','pytest','-q',*tests],cwd=stage,env=env)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(dict(model='APPLICATION_PREPARATION_VALIDATION_V1',
            status='PASS' if result.returncode==0 else 'FAIL',returncode=result.returncode,
            files=manifest['files'],production_execution_enabled=False,applied=False),stream,indent=2)
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
