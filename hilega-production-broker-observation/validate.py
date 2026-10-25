"""Run on the user's VM only. Does not start services or submit orders."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 stage=a.stage.resolve();a.output.parent.mkdir(parents=True,exist_ok=True)
 manifest=json.loads((Path(__file__).parent/'manifest.json').read_text())
 hashes={n:hashlib.sha256((stage/n).read_bytes()).hexdigest() for n in manifest['files']}
 if hashes!=manifest['files']:raise SystemExit('STAGED_FILES_DO_NOT_MATCH_PACKAGE')
 env=dict(os.environ,HILEGA_PRODUCTION_BROKER_OBSERVE='0',PYTHONPATH=str(stage/'backend')+os.pathsep+str(Path.cwd()))
 results=[]
 commands=[['.venv/bin/python','-m','pytest','-q',str(stage/'tests/test_hilega_production_broker_observation_v1.py'),str(stage/'tests/test_hilega_production_control_foundation_v1.py'),str(stage/'tests/test_hilega_production_workspace_v1.py'),str(stage/'tests/test_hilega_combined_promotion.py'),str(stage/'tests/test_hilega_execution_dispatch_validation.py')],['npm','--prefix',str(stage/'frontend'),'run','build']]
 for command in commands:
  result=subprocess.run(command,env=env)
  results.append(dict(step='tests' if '-m' in command else 'frontend_build',exit_code=result.returncode))
  if result.returncode:break
 report=dict(model='HILEGA_BROKER_OBSERVATION_VALIDATION_V1',status='PASS' if len(results)==2 and all(r['exit_code']==0 for r in results) else 'FAIL',steps=results,files=hashes,orders_sent=False,services_started=False,production_ready=False)
 a.output.write_text(json.dumps(report,indent=2));print(json.dumps(dict(status=report['status'],report=str(a.output))))
 if report['status']!='PASS':raise SystemExit(1)
if __name__=='__main__':main()
