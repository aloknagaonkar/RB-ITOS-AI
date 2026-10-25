"""VM-only offline validation. Never contacts Upstox or starts services."""
import argparse,hashlib,json,os,subprocess,tempfile
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    stage=a.stage.resolve();root=Path.cwd();manifest=json.loads((Path(__file__).parent/'manifest.json').read_text())
    hashes={n:hashlib.sha256((stage/n).read_bytes()).hexdigest() for n in manifest['files']}
    if hashes!=manifest['files']:raise SystemExit('STAGED_FILES_DO_NOT_MATCH_PACKAGE')
    for name,expected in manifest.get('requires',{}).items():
        if hashlib.sha256((stage/name).read_bytes()).hexdigest()!=expected:raise SystemExit('STAGED_DEPENDENCY_CHANGED')
    env=dict(os.environ,HILEGA_PRODUCTION_BROKER_OBSERVE='0',PYTHONPATH=str(stage/'backend')+os.pathsep+str(root))
    tests=['test_hilega_production_account_adapter_v1.py','test_hilega_production_ownership_v1.py','test_hilega_production_broker_observation_v1.py',
           'test_hilega_production_control_foundation_v1.py','test_hilega_production_workspace_v1.py',
           'test_hilega_combined_promotion.py','test_hilega_execution_dispatch_validation.py']
    command=[str(root/'.venv/bin/python'),'-m','pytest','-q',*[str(stage/'tests'/n) for n in tests]]
    steps=[];r=subprocess.run(command,env=env);steps.append(dict(step='offline_tests',exit_code=r.returncode))
    status='PASS' if r.returncode==0 else 'FAIL'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(dict(model='HILEGA_ACCOUNT_ADAPTER_VALIDATION_V1',status=status,
        files=hashes,steps=steps,orders_sent=False,services_started=False,production_ready=False),indent=2))
    print(json.dumps(dict(status=status,report=str(a.output))))
    raise SystemExit(0 if status=='PASS' else 1)
if __name__=='__main__':main()
