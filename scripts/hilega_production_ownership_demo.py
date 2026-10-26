"""Synthetic offline lifecycle demonstration. Never reads tokens or contacts Upstox."""
import argparse,json
from pathlib import Path
from market_lab.hilega_production_ownership_v1 import Ledger

DAY='2026-10-25'
def at(t):return DAY+'T'+t+':00+05:30'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise SystemExit('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    l=Ledger(a.output/'ownership-fixture.sqlite','synthetic-account-only')
    e=l.register_entry(signal_id='synthetic-bearish-signal',signal_at=at('09:20'),intent_at=at('09:25'),
        direction='BEARISH',instrument='TEST_FO|SYNTHETIC_PE',product='I',quantity_=65,
        policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='OFFLINE_FIXTURE_ONLY')
    rows=[];proof=[]
    def order(oid,side,q,filled,pending,status):return dict(order_id=oid,instrument='TEST_FO|SYNTHETIC_PE',product='I',side=side,quantity=q,filled=filled,pending=pending,status=status)
    def trade(oid,tid,side,q,price,time):return dict(order_id=oid,trade_id=tid,instrument='TEST_FO|SYNTHETIC_PE',product='I',side=side,quantity=q,price=price,filled_at=at(time))
    def snap(sid,time,orders,trades,q):return dict(snapshot_id=sid,observed_at=at(time),account_scope=l.account,evidence_mode='OFFLINE_FIXTURE',complete=True,orders=orders,trades=trades,positions=[dict(instrument='TEST_FO|SYNTHETIC_PE',product='I',quantity=q)])
    def step(label,s,expected,reason=None):
        r=l.reconcile(s,as_of=s['observed_at']);ok=r['status']==expected and (reason is None or r.get('reason')==reason)
        position=(r.get('positions') or [{}])[0]
        rows.append([label,r['status'],r.get('reason','—'),position.get('remaining','Unknown'),position.get('gross_realised_premium_value','Unknown')])
        proof.append(dict(step=label,pass_=ok,result=r));return ok
    ok=step('Accepted response unknown',snap('S0','09:25',[],[],0),'REVIEW_REQUIRED','ORDER_ACCEPTANCE_UNKNOWN_NO_RESUBMISSION')
    l.bind_order(intent_id=e,order_id='TEST-B1',at=at('09:25'))
    b=trade('TEST-B1','TB1','BUY',20,'100','09:25')
    ok=step('Partial entry: 20 of 65',snap('S1','09:26',[order('TEST-B1','BUY',65,20,45,'PARTIAL')],[b],20),'RECONCILED_OFFLINE_FIXTURE') and ok
    sell1=order('TEST-E1','SELL',10,10,0,'FILLED');f1=trade('TEST-E1','TE1','SELL',10,'105','09:27')
    cancelled=order('TEST-B1','BUY',65,20,0,'CANCELLED')
    ok=step('Unmapped external exit',snap('S2','09:28',[cancelled,sell1],[b,f1],10),'REVIEW_REQUIRED','UNMAPPED_ACTIVITY_ON_OWNED_INSTRUMENT') and ok
    x=l.register_exit(entry_id=e,exit_key='verified-external-A',intent_at=at('09:27'),quantity_=10,reason='EXPLICIT_FIXTURE_EXTERNAL_EXIT_MAPPING',external=True,actor='synthetic-operator')
    l.bind_order(intent_id=x,order_id='TEST-E1',at=at('09:28'))
    ok=step('Explicit external mapping',snap('S3','09:28',[cancelled,sell1],[b,f1],10),'RECONCILED_OFFLINE_FIXTURE') and ok
    x=l.register_exit(entry_id=e,exit_key='remaining-close',intent_at=at('09:29'),quantity_=10,reason='FIXTURE_CLOSE_REMAINING')
    l.bind_order(intent_id=x,order_id='TEST-E2',at=at('09:29'))
    sell2=order('TEST-E2','SELL',10,10,0,'FILLED');f2=trade('TEST-E2','TE2','SELL',10,'107','09:29')
    final=snap('S4','09:30',[cancelled,sell1,sell2],[b,f1,f2],0)
    ok=step('Remaining 10 closed',final,'RECONCILED_OFFLINE_FIXTURE') and ok
    ok=step('Duplicate snapshot',final,'IDEMPOTENT_REPLAY') and ok
    stale=l.report(as_of=at('09:31'));ok=ok and stale['state']['status']=='STALE' and not stale['entry_permission']
    rows.append(['One minute later: stale','STALE','Evidence unavailable','Unknown','Unknown'])
    report=dict(status='PASS' if ok else 'FAIL',evidence_mode='OFFLINE_FIXTURE',steps=proof,
        final_report=l.report(as_of=at('09:30')),stale_report=stale,production_execution_enabled=False,orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Ownership reconciliation — synthetic fixtures only','',
           'No actual strategy replay, market prices, tokens or broker requests. No orders sent.',
           'Gross premium value is synthetic currency arithmetic, NOT NIFTY points or net broker P&L.','',
           '| Stage | Status | Reason | Verified remaining quantity | Synthetic gross realised premium value |',
           '|---|---|---|---:|---:|']
    lines+=['| '+' | '.join(map(str,r))+' |' for r in rows]
    lines+=['','Automatic external-exit attribution is not implemented. Mapping above is explicit fixture evidence.',
            'Entry permission and reversal BUY permission remain false throughout.','', 'Result: '+report['status']]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text)
    raise SystemExit(0 if ok else 1)
if __name__=='__main__':main()
