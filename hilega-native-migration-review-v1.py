"""Read-only native Hilega migration review. No application imports or broker calls."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ENV_KEYS={'LIVE_SHADOW_STRATEGY','HILEGA_PRODUCTION_WORKSPACE_MODE','HILEGA_STRIKE_SELECTOR_MODE',
          'HILEGA_MARKET_EVIDENCE_ENABLED','MIDPOINT_SHADOW_ENABLED'}
CONTROL_KEYS={'model','session_date','strategy_id','strategy_version','policy_id','execution_mode',
              'armed','enabled','entries_blocked','automatic_fill_ledger_version','strike_policy_version'}
UNITS=('hilega-api.service','hilega-worker.service','hilega-production-source-worker.service',
       'hilega-observation-analytics.service','hilega-observation-readiness.service',
       'hilega-lifecycle-reference.service','hilega-rsi-two-route-shadow.service')


def settings(repo):
    result={};path=repo/'.env'
    if not path.is_file() or path.is_symlink():return result
    for raw in path.read_text().splitlines():
        line=raw.strip()
        if line.startswith('export '):line=line[7:].lstrip()
        key,sep,value=line.partition('=')
        if sep and key.strip() in ENV_KEYS:
            result[key.strip()]=value.strip().strip('"\'')
    return result


def regular(repo,path):
    if path.is_symlink() or not path.is_file():return False
    return not any(p.is_symlink() for p in path.absolute().parents) and path.resolve().is_relative_to(repo.resolve())


def source_files(repo):
    paths=set()
    for relative,suffixes in (('backend/market_lab',{'.py'}),('frontend/src',{'.ts','.tsx','.css'})):
        root=repo/relative
        for path in root.rglob('*'):
            if path.suffix in suffixes and '__pycache__' not in path.parts and regular(repo,path):paths.add(path)
    for relative in ('frontend/package.json','frontend/package-lock.json','frontend/tsconfig.json',
                     'frontend/tsconfig.app.json','frontend/tsconfig.node.json','frontend/vite.config.ts',
                     'hilega-operational-lifecycle-tools-6cexrur_/manifest.json'):
        path=repo/relative
        if regular(repo,path):paths.add(path)
    for relative in ('hilega-operational-lifecycle-tools-6cexrur_','hilega-reference-service-stage-yup3_wr1'):
        for path in (repo/relative).glob('*.py'):
            if regular(repo,path):paths.add(path)
    return sorted(paths)


def control_summary(repo):
    out={}
    for rel in ('data/live-observation/hilega-upstox-sandbox-v2/control.json',
                'data/live-observation/hilega-upstox-sandbox-v1/live-control.json'):
        path=repo/rel
        if regular(repo,path):
            try:
                body=json.loads(path.read_text())
                out[rel]={k:v for k,v in body.items() if k in CONTROL_KEYS and isinstance(v,(str,bool,int,float,type(None)))}
            except (ValueError,AttributeError):out[rel]={'status':'UNREADABLE'}
    return out


def service_states():
    out={}
    for name in UNITS:
        try:
            r=subprocess.run(['systemctl','--user','show',name,'-p','ActiveState,SubState,MainPID,WorkingDirectory'],
                capture_output=True,text=True,timeout=15)
            out[name]={k:v for line in r.stdout.splitlines() if '=' in line for k,v in [line.split('=',1)]
                       if k in {'ActiveState','SubState','MainPID','WorkingDirectory'}}
        except (OSError,subprocess.TimeoutExpired):out[name]={'status':'UNAVAILABLE'}
    return out


def collect(repo,output=None,include_services=True):
    repo=repo.resolve()
    if not (repo/'backend/market_lab').is_dir() or not (repo/'frontend/src').is_dir():
        raise ValueError('RUN_FROM_RB_ITOS_AI_REPOSITORY')
    paths=source_files(repo)
    report=dict(model='HILEGA_NATIVE_MIGRATION_REVIEW_V1',created_at=datetime.now().astimezone().isoformat(),
        selected_settings=settings(repo),execution_controls=control_summary(repo),
        services=service_states() if include_services else {},
        source_sha256={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        active_position_state='NOT_CAPTURED; MUST VERIFY CURRENT POSITIONS AND PENDING ORDERS BEFORE CUTOVER',
        application_files_modified=False,services_changed=False,broker_calls=False,
        scope='Replace current Hilega strategy in existing live shadow/historical screens; preserve execution route and manual controls')
    target=output or repo/'data/recovery'/('hilega-native-source-review-'+datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.zip')
    target=target.absolute();target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise ValueError('REVIEW_ARCHIVE_ALREADY_EXISTS')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        archive.writestr('review.json',json.dumps(report,indent=2)+'\n')
        for path in paths:archive.write(path,'source/'+str(path.relative_to(repo)))
    return dict(status='READ_ONLY_REVIEW_EXPORTED',archive=str(target),source_files=len(paths),
        selected_settings=report['selected_settings'],execution_controls=report['execution_controls'],
        services=report['services'],application_files_modified=False,services_changed=False,broker_calls=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--output',type=Path)
    a=p.parse_args();print(json.dumps(collect(a.repo,a.output),indent=2))
if __name__=='__main__':main()
