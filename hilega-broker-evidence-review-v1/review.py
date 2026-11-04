"""Offline signed-capture review and broker evidence request; never clears execution gates."""
import argparse,hashlib,hmac,importlib.util,json,os,stat,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from compare import compare_trade
sys.dont_write_bytecode=True
def need(ok,reason):
    if not ok:raise ValueError(reason)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_SOURCE_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(raw(p))
def private(p):
    b=raw(p);s=p.stat();need(s.st_uid==os.getuid() and s.st_nlink==1 and stat.S_IMODE(s.st_mode)&0o077==0,'PRIVATE_OWNED_EVIDENCE_REQUIRED');return b

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);ap.add_argument('--evidence-review',type=Path,required=True);ap.add_argument('--finance-review',type=Path,required=True);ap.add_argument('--pin-file',type=Path,default=Path.home()/'hilega-private/upstox-account-pin.json');a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute()
    for n,h in load(here/'MANIFEST.json').items():need(sha(raw(here/n))==h,'EVIDENCE_REVIEW_PACKAGE_CHANGED')
    for n,h in load(here/'BASELINE-PINS.json').items():need(sha(raw(root/n))==h,'EVIDENCE_REVIEW_BASELINE_CHANGED')
    need(sha(raw(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=load(path);need(plan['model']=='HILEGA_WARMUP_PREVENTION_INSTALL_V1' and plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_SUCCESSOR_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-broker-evidence-review-',dir=root));out.chmod(0o700)
    def save(name,value):
        fd=os.open(out/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:f.write(value if isinstance(value,str) else json.dumps(value,indent=2));f.write('\n')
    def status(label):
        r=subprocess.run([sys.executable,'-B',str(root/'hilega-warmup-prevention-deploy-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256],capture_output=True,text=True,timeout=110);save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));need(r.returncode==0 and json.loads(r.stdout)['phase']=='CLOSED_WARMUP_PREVENTION_RUNNING','CURRENT_CLOSED_RUNTIME_CHECK_FAILED')
    status('BEFORE')
    folder=root/'hilega-issuer-provision-v1';sys.path.insert(0,str(folder));spec=importlib.util.spec_from_file_location('evidence_release_reader',folder/'manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);bundle=m.verify_release(plan)
    sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime')]
    from market_lab import hilega_production_account_adapter_v1 as api
    private(a.pin_file.absolute());pin=api.read_pin(a.pin_file.absolute())
    evidence_path=a.evidence_review.absolute()/'PRIVATE-ACCOUNT-BOUND-EVIDENCE.json';finance_path=a.finance_review.absolute()/'PRIVATE-POSTTRADE-EVIDENCE.json'
    need(evidence_path.parent.parent==root and finance_path.parent.parent==root,'REPOSITORY_EVIDENCE_REQUIRED')
    fingerprints={str(p):sha(private(p)) for p in (evidence_path,finance_path)}
    def verify(p,model):
        v=json.loads(private(p));signature=v.pop('signature',None);need(isinstance(signature,str) and hmac.compare_digest(signature,api.sign(v,pin)),'LOCAL_CAPTURE_SIGNATURE_INVALID');need(v['model']==model and v['account_scope']==pin['scope'] and v['production_execution_enabled'] is False,'ACCOUNT_SCOPE_OR_CAPTURE_MODEL_CHANGED');return v,signature
    evidence,evidence_sig=verify(evidence_path,'HILEGA_ACCOUNT_BOUND_TIMESTAMP_AUDIT_V1');finance,finance_sig=verify(finance_path,'HILEGA_ACCOUNT_BOUND_HISTORICAL_FINANCE_V1')
    need(finance['session']=='2026-11-02' and finance['prior_evidence_signature']==evidence_sig,'EXACT_SESSION_AND_CAPTURE_LINK_REQUIRED')
    need(datetime.fromisoformat(evidence['completed_at']).astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()=='2026-11-02','EXPECTED_PRIOR_ACTIVITY_DATE_REQUIRED')
    trades=api.response_data(evidence['raw_trades'],'trades',list);details=evidence['per_order_details'];comparisons=[]
    for ordinal,oid in enumerate(sorted(details),1):
        d=details[oid]
        for t in trades:
            if t.get('order_id')==oid:comparisons.append(dict(order_ordinal=ordinal,**compare_trade(t,d['order_trades']['data'],d['history']['data'])))
    # Recompute aggregate arithmetic using the same pinned read-only finance reviewer.
    spec=importlib.util.spec_from_file_location('recorded_finance_reviewer',root/'hilega-live-prerequisites-v2/finance.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
    rows=[]
    for page in finance['raw_pages']:rows.extend(page['data'])
    aggregate=f.review(finance['raw_charges'],rows,finance['raw_metadata']['data']['trades_count'])
    aggregate['component_arithmetic_state']='NOT_ASSESSABLE_NULL_COMPONENTS' if aggregate['missing_or_null_components'] else ('MATCH' if aggregate['aggregate_component_arithmetic_matches'] else 'MISMATCH')
    saved=finance['review'];corroboration=saved.get('historical_trade_corroboration') or {}
    summary=dict(status='SIGNED_CAPTURE_REVIEW_COMPLETE_EXTERNAL_EVIDENCE_REQUIRED',session='2026-11-02',signed_local_capture_signatures_verified=True,captures_linked_to_same_account_and_session=True,broker_independent_signature_or_report_finality_verified=False,recorded_cross_endpoint_fill_comparisons=comparisons,aggregate_review=aggregate,historical_trade_capture_complete=saved.get('historical_trade_capture_complete') is True,recorded_historical_matches=corroboration.get('matching_trade_id_exchange_side_quantity_price_rows'),operator_activity_attribution='USER_REPORTED_MANUAL_FOR_2026_11_02_ONLY',strategy_ownership_verified=False,broker_timezone_contract_confirmed=False,actual_fees_reconciled=False,per_trade_fee_attribution_verified=False,full_contract_identity_verified=False,final_contract_note_supplied_to_this_review=False,broker_reply_supplied_to_this_review=False,capture_verification_key_loaded=True,broker_access_token_loaded=False,broker_requests_issued=False,timestamps_shifted=False,null_fee_components_converted_to_zero=False,source_fingerprints=fingerprints,application_sources_modified=False,services_changed=False,controller_resumed=False,orders_sent=False,production_execution_enabled=False,production_ready=False,audit_folder=str(out))
    requests=dict(session='2026-11-02',documents_required=[dict(kind='BROKER_TIMESTAMP_REPLY',required=['Broker case reference and response date','Timezone/offset contract for daily trade and per-order trade order_timestamp and exchange_timestamp','Timezone contract for order history; explanation of the exact 5h30m discrepancy']),dict(kind='FINAL_CONTRACT_NOTE_OR_ITEMIZED_REPORT',required=['Statement finality and session/account scope','Exact instrument identifier, expiry, strike, CE/PE, quantity and price for each fill','Final component charges including IPFT treatment','Explicit per-fill attribution or broker documented allocation method with rounding and coverage'])],user_confirmation_recorded='Manual activity for Nov 2 only; not Hilega strategy ownership proof',redaction_guidance='Do not share access tokens, signing keys, login credentials, PAN, address or bank details. Retain a consistent masked account reference and enough fill/contract fields for matching.',automatic_document_acceptance=False,fee_or_timestamp_override_available=False)
    draft='''# Upstox support questions — draft, not sent\n\nPlease clarify timestamp and final charge semantics for account activity on 2 November 2026. We retained raw API responses without shifting timestamps.\n\nFor two uniquely matched fills, order history shows 13:09:33 and 13:58:06, while daily and per-order trade exchange_timestamp shows 18:39:33 and 19:28:06, exactly 5h30m later. Which timezone/offset applies to each timestamp field? Is a conversion defect involved? Please identify the documented contract and any correction or version boundary. Identifiers can be provided privately in the broker support channel.\n\nThe charges API returns charges.ipft=null. What does null represent, where (if anywhere) is that component included, and what establishes report finality? Which final contract note/report and documented method support exact per-fill component attribution, including rounding? We have not treated null as zero or aggregate net cashflow as certified strategy P&L.\n\nPlease also clarify historical trade pagination reporting total_pages=0 while total_records=2 and page_size=100. We retained the raw metadata and verified the collected row count, without assuming the zero-page semantics.\n'''
    pair_lines=['- Order field: '+str(c.get('day_trade_order_timestamp'))+'; trade exchange field: '+str(c.get('day_trade_exchange_timestamp')) for c in comparisons]
    draft+='\n## Values recomputed from the verified saved capture\n\n'+'\n'.join(pair_lines)+'\n'
    save('BROKER-QUESTIONS.md',draft);save('EVIDENCE-REQUEST.json',requests)
    save('MILESTONES.md','''# Group 2 milestone snapshot\n\n- [x] Warmup repair/prevention deployed; closed successor runtime checked in this review.\n- [x] Existing timestamp and finance captures locally signature-verified and linked.\n- [x] Aggregate finance arithmetic recomputed without converting null components to zero.\n- [x] Manual attribution recorded only as user report for Nov 2.\n- [ ] Broker timezone reply received and validated.\n- [ ] Final contract note, report finality and exact component attribution verified.\n- [ ] Full historical contract identity reconciled.\n- [ ] v4 open-session WebSocket/managed observer qualification (reminder active).\n- [ ] Production contract admission, fresh seed/enrollment and final activation readiness.\n\nController paused; execution disabled. Support draft is not sent; no external blockers are cleared by this packet.\n''')
    for p,digest in fingerprints.items():need(sha(private(Path(p)))==digest,'CAPTURE_CHANGED_DURING_REVIEW')
    del pin
    status('AFTER');save('RESULT.json',summary)
    public={k:v for k,v in summary.items() if k not in {'recorded_cross_endpoint_fill_comparisons','source_fingerprints'}};public.update(fill_comparison_count=len(comparisons),support_draft=str(out/'BROKER-QUESTIONS.md'),evidence_request=str(out/'EVIDENCE-REQUEST.json'),milestones=str(out/'MILESTONES.md'),support_message_sent=False)
    print(json.dumps(public,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        code=str(exc).split(':',1)[0];print(json.dumps(dict(status='BROKER_EVIDENCE_REVIEW_BLOCKED',reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'INSPECT_BROKER_REVIEW_AUDIT',error_type=type(exc).__name__,location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],execution_enabled=False)));raise SystemExit(2)
