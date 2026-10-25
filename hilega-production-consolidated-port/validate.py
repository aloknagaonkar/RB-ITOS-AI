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
    env=dict(os.environ,HILEGA_PRODUCTION_WORKSPACE_MODE='DISABLED',HILEGA_PRODUCTION_BROKER_OBSERVE='0',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='0',PYTHONPATH=str(stage/'backend')+os.pathsep+str(root))
    env={k:v for k,v in env.items() if 'TOKEN' not in k and 'SECRET' not in k}
    tests=['test_hilega_consolidated_port_v1.py','test_hilega_consolidated_adapter_v1.py','test_hilega_durable_integration_v1.py','test_hilega_central_sim_allocation_v1.py','test_hilega_production_bridge_health_v1.py','test_hilega_production_simulator_bridge_v1.py','test_hilega_production_account_adapter_v1.py','test_hilega_production_ownership_v1.py','test_hilega_production_broker_observation_v1.py',
           'test_hilega_production_control_foundation_v1.py','test_hilega_production_workspace_v1.py',
           'test_hilega_combined_promotion.py','test_hilega_execution_dispatch_validation.py']
    command=[str(root/'.venv/bin/python'),'-m','pytest','-q',*[str(stage/'tests'/n) for n in tests]]
    steps=[];r=subprocess.run(command,env=env,cwd=stage);steps.append(dict(step='offline_tests',exit_code=r.returncode))
    if r.returncode==0:
        with tempfile.TemporaryDirectory(prefix='hilega-simulator-bridge-demo-') as tmp:
            r=subprocess.run([str(root/'.venv/bin/python'),str(stage/'scripts/hilega_production_simulator_bridge.py'),'--demo','--output',str(Path(tmp)/'demo')],env=env,cwd=stage)
            steps.append(dict(step='synthetic_lifecycle_demo',exit_code=r.returncode))
    if len(steps)==2 and all(x['exit_code']==0 for x in steps):
        with tempfile.TemporaryDirectory(prefix='hilega-bridge-health-demo-') as tmp:
            r=subprocess.run([str(root/'.venv/bin/python'),str(stage/'scripts/hilega_production_bridge_health_demo.py'),'--output',str(Path(tmp)/'demo')],env=env,cwd=stage)
            steps.append(dict(step='heartbeat_lifecycle_demo',exit_code=r.returncode))
    if len(steps)==3 and all(x['exit_code']==0 for x in steps):
        with tempfile.TemporaryDirectory(prefix='hilega-central-allocation-demo-') as tmp:
            r=subprocess.run([str(root/'.venv/bin/python'),str(stage/'scripts/hilega_central_allocation_demo.py'),'--output',str(Path(tmp)/'demo')],env=env,cwd=stage)
            steps.append(dict(step='central_allocation_demo',exit_code=r.returncode))
    if len(steps)==4 and all(x['exit_code']==0 for x in steps):
        with tempfile.TemporaryDirectory(prefix='hilega-consolidated-port-demo-') as tmp:
            r=subprocess.run([str(root/'.venv/bin/python'),str(stage/'scripts/hilega_consolidated_port_demo.py'),'--output',str(Path(tmp)/'demo')],env=env,cwd=stage)
            steps.append(dict(step='consolidated_port_demo',exit_code=r.returncode))
    if len(steps)==5 and all(x['exit_code']==0 for x in steps):
        r=subprocess.run(['npm','--prefix',str(stage/'frontend'),'run','build'],env=env,cwd=stage)
        steps.append(dict(step='frontend_build',exit_code=r.returncode))
    status='PASS' if len(steps)==6 and all(x['exit_code']==0 for x in steps) else 'FAIL'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(dict(model='HILEGA_CONSOLIDATED_PORT_VALIDATION_V1',status=status,
        files=hashes,steps=steps,orders_sent=False,services_started=False,production_ready=False),indent=2))
    print(json.dumps(dict(status=status,report=str(a.output))))
    raise SystemExit(0 if status=='PASS' else 1)
if __name__=='__main__':main()
