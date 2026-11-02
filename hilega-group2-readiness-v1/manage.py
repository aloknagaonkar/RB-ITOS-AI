"""Group 2 read-only readiness. Optional fixed-endpoint broker GET capture; no order actions."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from readiness import collect,milestone,cash_preview


def need(ok,reason):
    if not ok:raise ValueError(reason)


def regular(path):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_GROUP2_INPUT_REQUIRED')
    return p.read_bytes()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def reference_paths(repo,plan):
    r=subprocess.run(['systemctl','--user','show','hilega-lifecycle-reference.service','--property=ExecStart','--value'],
        capture_output=True,text=True,timeout=10)
    need(r.returncode==0 and 'argv[]=' in r.stdout,'REFERENCE_COMMAND_NOT_RECOGNIZED')
    argv=shlex.split(r.stdout.split('argv[]=',1)[1].split(' ;',1)[0])
    def value(flag):
        need(argv.count(flag)==1 and argv.index(flag)+1<len(argv),'UNIQUE_REFERENCE_PATH_ARGUMENT_REQUIRED')
        return Path(argv[argv.index(flag)+1]).absolute()
    need(value('--repo')==repo and value('--application')==Path(plan['application_db'])
        and value('--adapter')==Path(plan['adapter_db']),'REFERENCE_SERVICE_DATABASE_BINDINGS_CHANGED')
    pin=value('--pin-file');env=value('--env-file')
    for path in (pin,env):need(path.is_file() and not any(p.is_symlink() for p in [path,*path.parents]),'REGULAR_REFERENCE_CREDENTIAL_PATH_REQUIRED')
    return pin,env


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--broker-read',action='store_true',help='Use the existing reference-service pin and token for fixed GET-only account/funds capture')
    args=p.parse_args();repo=args.repo.resolve();folder=Path(__file__).resolve().parent
    for n,d in json.loads(regular(folder/'MANIFEST.json')).items():need(sha(regular(folder/n))==d,'GROUP2_PACKAGE_CHANGED')
    for n,d in json.loads(regular(folder/'BASELINE_PINS.json')).items():need(sha(regular(repo/n))==d,'VERIFIED_CLOSED_DEPLOYMENT_TOOLS_CHANGED')
    g1=json.loads(regular(repo/'hilega-group1-cache-recovery-v1/VM-VALIDATION.json'))
    need(g1['status']=='GROUP1_ROLLBACK_AND_READ_ONLY_CANDIDATE_RESTORE_PASS' and g1['group1_closed_worker_deployment_complete'] is True,'COMPLETE_CLOSED_WORKER_GROUP1_RECEIPT_REQUIRED')
    active=Path(g1['active_plan']);raw=regular(active);digest=g1['active_plan_sha256'];need(sha(raw)==digest,'ACTIVE_CLOSED_PLAN_CHANGED');plan=json.loads(raw)
    need(plan['repo']==str(repo) and plan['production_execution_enabled'] is False,'ACTIVE_CLOSED_PLAN_REQUIRED')
    tool=repo/'hilega-group1-rollout-v1';tool_manifest=regular(tool/'MANIFEST.json')
    need(sha(tool_manifest)==plan['tool_manifest_sha256'],'ACTIVE_ROLLOUT_TOOL_CHANGED')
    for n,d in json.loads(tool_manifest).items():need(sha(regular(tool/n))==d,'ACTIVE_ROLLOUT_CODE_CHANGED')
    audit=Path(tempfile.mkdtemp(prefix='hilega-group2-review-',dir=repo));audit.chmod(0o700)
    (audit/'.gitignore').write_text('*\n')
    def health(label):
        r=subprocess.run([sys.executable,str(tool/'manage.py'),'--repo',str(repo),'--action','status',
            '--plan',str(active),'--approve-plan-sha256',digest],cwd=repo,capture_output=True,text=True,timeout=60)
        need(r.returncode==0,'CURRENT_CLOSED_DEPLOYMENT_REQUIRES_REVIEW')
        value=json.loads(r.stdout);need(value['phase']=='CLOSED_BUNDLE_RUNNING' and value['production_execution_enabled'] is False,'VERIFIED_CLOSED_WORKER_REQUIRED')
        save(audit/(label+'.json'),value)
    health('CLOSED-BASELINE-BEFORE')
    with tempfile.TemporaryDirectory() as tmp:
        junit=Path(tmp)/'junit.xml';code=subprocess.run([sys.executable,'-m','pytest',str(folder/'test_readiness.py'),'-q','--junitxml='+str(junit)],cwd=repo).returncode
        cases=list(ET.parse(junit).getroot().iter('testcase')) if junit.is_file() else []
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases);skipped=sum(c.find('skipped') is not None for c in cases)
    need(code==0 and len(cases)==12 and failed==skipped==0,'GROUP2_CANDIDATE_TESTS_REQUIRE_REVIEW')
    summary=None;failure=None;paths_discovered=False;evidence_saved=False
    try:
        pin_path,env_path=reference_paths(repo,plan);paths_discovered=True
        if args.broker_read:
            sys.dont_write_bytecode=True
            bundle=Path(plan['destination']);sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
            api=importlib.import_module('market_lab.hilega_production_account_adapter_v1')
            observation=importlib.import_module('market_lab.hilega_production_broker_observation_v1')
            contracts=json.loads(regular(folder/'API-CONTRACTS.json'))
            for module,name in [(api,'hilega_production_account_adapter_v1.py'),(observation,'hilega_production_broker_observation_v1.py')]:
                expected=bundle/'backend/market_lab'/name
                need(Path(module.__file__).resolve()==expected,'EXACT_BUNDLED_READ_ONLY_CLIENT_REQUIRED')
                need(sha(regular(expected))==contracts['source_sha256'][name],'REVIEWED_BROKER_READ_CLIENT_CHANGED')
            need(observation.PATHS==contracts['paths'] and api.Client is observation.Client,'FIXED_GET_ONLY_ENDPOINTS_REQUIRED')
            pin=api.read_pin(pin_path);need(api.aware(pin['approved_at'])<=datetime.now(timezone.utc),'FUTURE_ACCOUNT_PIN_NOT_ALLOWED')
            with closing(sqlite3.connect(Path(plan['adapter_db']).as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('PRAGMA query_only=ON');meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
                need(meta==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'BROKER_PIN_AND_LOCAL_ADAPTER_SCOPE_MISMATCH')
            info=env_path.stat();need(info.st_uid==os.getuid() and stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)&0o077==0,'TOKEN_ENV_FILE_MUST_BE_OWNER_PRIVATE')
            from dotenv import dotenv_values
            settings=dotenv_values(env_path)
            token=(settings.get('HILEGA_PRODUCTION_BROKER_READ_TOKEN') or settings.get('UPSTOX_ACCESS_TOKEN') or '').strip()
            need(bool(token) and '\n' not in token and '\r' not in token,'EXISTING_BROKER_READ_TOKEN_REQUIRED')
            client=api.Client(token);del token,settings
            evidence,summary=collect(client,pin,api,observation)
            health('CLOSED-BASELINE-AFTER')
            private=audit/'private';private.mkdir(mode=0o700)
            save(private/'SIGNED-ACCOUNT-CASH-EVIDENCE.json',evidence)
            save(private/'CASH-PREVIEW.json',cash_preview(evidence['funds_after']['cash_available_to_trade'],0))
            evidence_saved=True
            del client,pin
    except Exception as exc:
        reason=str(exc);safe=reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,199}',reason) else 'GROUP2_READ_CONTEXT_OR_CAPTURE_UNAVAILABLE'
        failure=dict(status='BROKER_READ_BLOCKED' if args.broker_read else 'READ_CONTEXT_REQUIRES_REVIEW',reason=safe,error_type=type(exc).__name__)
    groups=milestone(summary);save(audit/'MILESTONES.json',groups)
    policy=dict(status='DRAFT_REQUIRES_OPERATOR_APPROVAL',unknown_outcome='NEVER_AUTOMATICALLY_RESUBMIT',
        partial_working='OBSERVE_EXISTING_ATTEMPT',cancelled_partial='MANUAL_RESIDUAL_REVIEW',
        reversal='EXIT_AND_VERIFY_FLAT_BEFORE_NEW_ENTRY',broker_cash_addback='NONE',
        fee_policy='NO_CLAIM_OF_COMPLETE_NET_PNL_WITHOUT_ATTRIBUTED_BROKER_CHARGES',
        trusted_authority_provisioned=False,local_random_key_is_not_production_trust=True,
        production_execution_enabled=False)
    save(audit/'POLICY-REVIEW.json',policy)
    report=dict(status='PASS_TARGETED_ONLY' if failure is None else 'GROUP2_READINESS_REQUIRES_REVIEW',
        scope='GROUP2_GET_ONLY_BROKER_EVIDENCE_AND_CONSERVATIVE_READINESS_CANDIDATES',assessed_at=datetime.now(timezone.utc).isoformat(),
        collected_cases=12,failed=0,skipped=0,prior_closed_release_cases_passed=314,prior_regression_reexecuted=False,
        reference_service_paths_discovered=paths_discovered,broker_read_requested=args.broker_read,
        actual_broker_get_capture_passed=summary is not None,broker_summary=summary,blocked=failure,
        private_signed_evidence_saved=evidence_saved,secret_values_exported=False,secret_material_created=False,
        trusted_production_authority_provisioned=False,execution_factory_configured=False,live_database_enrolled=False,
        conservative_order_policy_candidate_tested=True,aggregate_fee_validator_tested=True,actual_fees_reconciled=False,
        cash_preview_candidate_tested=True,broker_cash_release_implemented=False,group2_complete=False,
        audit_folder=str(audit),active_closed_plan=str(active),application_services_changed=False,
        installed_sources_modified=False,application_sql_mutations_issued=False,controller_resumed=False,
        orders_sent=False,production_execution_enabled=False,production_ready=False)
    save(audit/'RESULT.json',report)
    destination=folder/'VM-VALIDATION.json';destination.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));print('Report:',destination)
    return 0 if failure is None else 1

if __name__=='__main__':raise SystemExit(main())
