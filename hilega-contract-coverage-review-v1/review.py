"""Offline contract-selection comparison using pinned installed rules and saved broker evidence."""
import argparse,hashlib,importlib.util,inspect,json,os,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.dont_write_bytecode=True
RULE_SHA='660c92d979626692898c4b154b3918be24ed6fe27424885f165ccd7ee45195e5'
INDEX='NSE_INDEX|Nifty 50'
def need(ok,code):
    if not ok:raise ValueError(code)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(raw(p))
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);ap.add_argument('--quote-review',type=Path,required=True);a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute();qroot=a.quote_review.absolute()
    for n,h in load(here/'MANIFEST.json').items():need(sha(raw(here/n))==h,'COVERAGE_TOOL_CHANGED')
    for n,h in load(here/'BASELINE-PINS.json').items():need(sha(raw(root/n))==h,'COVERAGE_BASELINE_CHANGED')
    need(sha(raw(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=load(path);need(plan['model']=='HILEGA_WARMUP_PREVENTION_INSTALL_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'SUPPORTED_CLOSED_SUCCESSOR_REQUIRED')
    need(qroot.parent==root and qroot.name.startswith('hilega-option-quote-readcheck-'),'EXPECTED_QUOTE_REVIEW_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-contract-coverage-review-',dir=root));out.chmod(0o700)
    def save(name,value):
        fd=os.open(out/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-warmup-prevention-deploy-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110);save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_WARMUP_PREVENTION_RUNNING','SUCCESSOR_STATUS_FAILED')
    status('BEFORE')
    issuer=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(issuer));bundle=module(issuer/'manage.py','coverage_release_reader').verify_release(plan)
    manifest=load(bundle/'RELEASE-MANIFEST.json');matches=[n for n in manifest['files'] if n.endswith('hilega-production-contract-preview/rules.py')]
    need(len(matches)==1,'UNIQUE_INSTALLED_CONTRACT_RULES_REQUIRED');rulepath=bundle/matches[0]
    need(sha(raw(rulepath))==RULE_SHA,'REVIEWED_CONTRACT_RULE_VERSION_CHANGED');rules=module(rulepath,'reviewed_contract_rules')
    names=['RESULT.json','PRIVATE-INDEX.json','PRIVATE-CONTRACTS.json',*[f'PRIVATE-QUOTES-{i}.json' for i in range(1,4)]]
    fingerprints={n:sha(raw(qroot/n)) for n in names};receipt=load(qroot/'RESULT.json');need(receipt['status']=='BOUNDED_REST_OPTION_QUOTE_EVIDENCE_PASS' and len(receipt['samples'])==3,'PASSING_REST_EVIDENCE_REQUIRED')
    initial=load(qroot/'PRIVATE-INDEX.json');index=rules.quote_map(initial['data'],[INDEX])[INDEX];spot=index['last_price'];contracts=load(qroot/'PRIVATE-CONTRACTS.json')['data'];at=datetime.fromisoformat(receipt['samples'][0]['received_at']);day=at.astimezone(ZoneInfo('Asia/Kolkata')).date()
    atm=rules.select(contracts,spot,[0],1,day);wide=rules.select(contracts,spot,[-2,-1,0,1,2],1,day);atmkeys={c['instrument_key'] for c in atm['contracts']};widekeys={c['instrument_key'] for c in wide['contracts']}
    defaults=inspect.signature(rules.assess).parameters;max_age=defaults['max_age'].default;max_spread=defaults['max_spread'].default
    samples=[]
    for i,s in enumerate(receipt['samples'],1):
        observed={c['instrument_key'] for c in s['contracts']};mapping=rules.quote_map(load(qroot/f'PRIVATE-QUOTES-{i}.json')['data'],sorted(observed));asof=datetime.fromisoformat(s['received_at']);quality=[]
        for c in wide['contracts']:
            if c['instrument_key'] not in mapping:
                quality.append(dict(instrument_key=c['instrument_key'],reasons=['NOT_IN_RECORDED_DIAGNOSTIC_BASKET']));continue
            try:
                result=rules.quality(mapping[c['instrument_key']],c['quantity'],asof,max_age,max_spread)
                quality.append(dict(instrument_key=c['instrument_key'],side=c['side'],quantity=c['quantity'],**result))
            except Exception as exc:
                import re
                code=str(exc).split(':',1)[0];quality.append(dict(instrument_key=c['instrument_key'],reasons=[code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'NATIVE_QUOTE_QUALITY_UNVERIFIED'],error_type=type(exc).__name__))
        samples.append(dict(recorded_at=s['received_at'],native_atm_contracts_present=atmkeys<=observed,native_five_strike_basket_exact_match=widekeys==observed,native_quote_quality_at_recorded_time=quality))
    for n,h in fingerprints.items():need(sha(raw(qroot/n))==h,'RECORDED_QUOTE_EVIDENCE_CHANGED')
    status('AFTER')
    report=dict(status='OFFLINE_NATIVE_CONTRACT_COVERAGE_COMPARISON_COMPLETE',rules_file=str(rulepath),rules_sha256=RULE_SHA,evidence_fingerprints=fingerprints,recorded_session=day.isoformat(),evidence_age_seconds=(datetime.now(timezone.utc)-at).total_seconds(),fresh_live_evidence=False,native_entry_preview_offsets=[0],native_observation_offsets=[-2,-1,0,1,2],native_atm_tie_rule=wide['atm_tie_rule'],diagnostic_stream_v3_tie_rule='LOWER_STRIKE',native_quantity_minimum_freeze_and_tick_metadata_validated=True,preview_quote_defaults=dict(max_age_seconds=max_age,max_spread_percent=str(max_spread)),preview_defaults_are_not_new_production_policy=True,recorded_basket_covers_native_atm_all_samples=all(s['native_atm_contracts_present'] for s in samples),recorded_wide_basket_exact_match_all_samples=all(s['native_five_strike_basket_exact_match'] for s in samples),samples=samples,saved_rest_capture_signature_or_independent_authenticity_verified=False,source_hashes_recorded=True,production_contract_admission_verified=False,strategy_ownership_verified=False,websocket_validated=False,policy_changed=False,broker_requests_issued=False,credentials_loaded=False,application_services_changed=False,controller_resumed=False,production_execution_enabled=False,production_ready=False,audit_folder=str(out))
    save('RESULT.json',report)
    public={k:v for k,v in report.items() if k not in {'samples','evidence_fingerprints'}}
    public['quality_summary']=[dict(recorded_at=s['recorded_at'],contracts_checked=len(s['native_quote_quality_at_recorded_time']),passing_contracts=sum(not r.get('reasons') for r in s['native_quote_quality_at_recorded_time']),reasons=sorted({r for q in s['native_quote_quality_at_recorded_time'] for r in q.get('reasons',[])})) for s in samples]
    print(json.dumps(public,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        code=str(exc).split(':',1)[0];print(json.dumps(dict(status='CONTRACT_COVERAGE_REVIEW_BLOCKED',reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'REVIEW_COVERAGE_AUDIT',error_type=type(exc).__name__,location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],live_changes_issued=False)));raise SystemExit(2)
