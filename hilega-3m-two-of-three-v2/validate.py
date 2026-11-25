"""VM-only staged tests, UI build and saved-session live/replay parity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import stage as staging

HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--stage',type=Path,required=True)
    p.add_argument('--days',nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();repo=args.repo.resolve();stage=args.stage.resolve();out=args.output.resolve()
    if staging.check(repo)['status']!='SOURCE_MATCH':raise ValueError('INSTALLED_SOURCE_CHANGED')
    receipt=json.loads((stage/'stage-receipt.json').read_text())
    if receipt.get('repo')!=str(repo) or receipt.get('status')!='STAGED_ONLY':raise ValueError('INVALID_STAGE_RECEIPT')
    manifest=json.loads((HERE/'manifest.json').read_text())
    for relative,digest in manifest['candidate_sha256'].items():
        if staging.digest(stage/relative)!=digest:raise ValueError('STAGED_SOURCE_CHANGED:'+relative)
    out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONPATH=str(stage/'backend'),PYTHONDONTWRITEBYTECODE='1')
    checks=[('candidate_tests',[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',
                str(HERE/'tests'),str(repo/'tests/test_hilega_milega_option_shadow_lifecycle_v1.py'),
                str(repo/'tests/test_hilega_sandbox_event_bridge_v1.py')]),
            ('frontend_build',['npm','--prefix',str(stage/'frontend'),'run','build']),
            ('saved_candle_comparison',[sys.executable,'-B',str(HERE/'compare.py'),'--repo',str(repo),
                '--stage',str(stage),'--days',*args.days,'--out',str(out/'comparison')])]
    report=dict(status='RUNNING',strategy_version=manifest['strategy_version'],checks=[],
        installed_files_modified=False,services_restarted=False,broker_execution_validated=False,
        production_release_ready=False)
    try:
        for name,command in checks:
            with (out/(name+'.log')).open('w') as log:
                run=subprocess.run(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
            report['checks'].append(dict(name=name,status='PASS' if run.returncode==0 else 'FAIL',log=str(out/(name+'.log'))))
            (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
            if run.returncode:raise ValueError('VALIDATION_FAILED:'+name+'; see '+str(out/(name+'.log')))
        for relative,digest in manifest['candidate_sha256'].items():
            if staging.digest(stage/relative)!=digest:raise ValueError('STAGED_SOURCE_CHANGED_DURING_VALIDATION:'+relative)
        report['status']='OFFLINE_VALIDATION_PASS'
        report['remaining']=['Review saved-session results','Compare any newer VM changes',
            'Validate actual broker exit submission deadline and confirmed flat state before enabling execution',
            'Controlled installation and service restart']
    except Exception as exc:
        report['status']='FAIL';report['error']=str(exc)
        raise
    finally:
        (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))

if __name__=='__main__':main()
