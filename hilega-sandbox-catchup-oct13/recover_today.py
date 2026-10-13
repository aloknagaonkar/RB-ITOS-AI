"""One-time October 13 catch-up basket using current Sandbox prices."""
import argparse,hashlib,json,sys,os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from filelock import FileLock
sys.path.insert(0,str(Path.cwd()/'backend'))
from dotenv import load_dotenv
from market_lab.hilega_sandbox_event_bridge_v1 import BridgeConfig,IntentStore,HilegaSandboxEventBridgeV1,_trade_id,ENTRY_EVENTS,EXIT_EVENTS
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from market_lab.hilega_upstox_sandbox_basket_v2 import BasketWorker,BasketTransport,strategy
from market_lab.hilega_upstox_sandbox_execution_v1 import SandboxConfig
IST=ZoneInfo('Asia/Kolkata');DAY='2026-10-13';AT=DAY+'T09:22:00+05:30';SID='HILEGA_V2_ALIGNMENT_DUAL_EXIT'

def active_entry(rows,now):
    if now.date().isoformat()!=DAY or now.strftime('%H:%M')>='14:50':raise ValueError('RECOVERY_ALLOWED_ONLY_OCT13_BEFORE_1450')
    rr=[r for r in rows if (r.get('payload') or {}).get('strategy_id')==SID and str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(DAY) and r.get('stage') in ('DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF') and r.get('status') in ('RECOVERED','PROCESSED','PASS')]
    rr.sort(key=lambda r:(str(r['payload'].get('decision_timestamp') or r.get('event_time','')),r.get('sequence',0)))
    candidates=[]
    for r in rr:
        p=r['payload'];at=p.get('decision_timestamp') or r.get('event_time','')
        if at>=AT:
            for ev in p.get('accepted_events') or []:
                if ev in EXIT_EVENTS:raise ValueError('ORIGINAL_RUN_HAS_EXITED_RECOVERY_BLOCKED')
                if ev in ENTRY_EVENTS:
                    if at!=AT or r['status']!='RECOVERED' or 'BEARISH' in ev:raise ValueError('DIFFERENT_ENTRY_OR_RUN_RECOVERY_BLOCKED')
                    candidates.append((r,ev))
    if not candidates:raise ValueError('ORIGINAL_RECOVERED_ENTRY_NOT_FOUND')
    p=rr[-1]['payload'];at=p.get('decision_timestamp') or rr[-1].get('event_time','')
    age=(now-datetime.fromisoformat(at)).total_seconds()
    if not 0<=age<=90 or p.get('trade_owner_after')!='BULLISH' or p.get('bullish_state')!='BULLISH_ACTIVE':raise ValueError('ACTIVE_BULLISH_EVIDENCE_MISSING_OR_STALE')
    return candidates[0]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args();load_dotenv('.env')
    loaded=BridgeConfig.from_env();cfg=BridgeConfig(True,loaded.source,loaded.output);store=ShadowStepAuditStoreV1(cfg.source);worker=BasketWorker();config=SandboxConfig.from_env(Path('.env'));config.assert_ready('SANDBOX_ONLY')
    with FileLock(str(worker.store.path)+'.worker.lock',timeout=10):
        # Same lock order as the serving worker: basket first, bridge second.
        HilegaSandboxEventBridgeV1(cfg).run_once()
        with IntentStore(cfg.output).lock:
            valid,reason=store.verify_chain()
            if not valid:raise ValueError('SOURCE_AUDIT_CHAIN_INVALID')
            now=datetime.now(IST);record,event=active_entry(store.read_all(),now);control=worker.control.read()
            if not control.get('armed') or control.get('kill_switch') or control.get('entries_blocked') or control.get('session_date')!=DAY or control.get('strategy_id')!=SID or strategy(worker.env)!=SID:raise ValueError('SANDBOX_CONTROL_NOT_READY')
            if int(record['sequence'])<=int(control['baseline_source_sequence']):raise ValueError('ORIGINAL_ENTRY_PRECEDES_ARM_BASELINE')
            intent_store=IntentStore(cfg.output);intents=intent_store.rows();journal=worker.store.rows()
            if worker.store.open_legs() or worker.store.uncertain():raise ValueError('OPEN_OR_UNCERTAIN_BASKET_RECOVERY_BLOCKED')
            if any(r.get('session_date')==DAY and r.get('event_type')=='ENTRY' for r in journal):raise ValueError('TODAY_ENTRY_ALREADY_ATTEMPTED_RECOVERY_BLOCKED')
            if any(r.get('event_timestamp','').startswith(DAY) and r.get('event_type')=='ENTRY' and r.get('decision')=='WOULD_SUBMIT' for r in intents):raise ValueError('TODAY_ENTRY_INTENT_ALREADY_EXISTS')
            intent_id=hashlib.sha256(f"{record['record_hash']}|{event}".encode()).hexdigest()
            intent=dict(model='HILEGA_SANDBOX_EVENT_BRIDGE_V1',intent_id=intent_id,event_id='HILEGA-RECOVERY-'+record['record_hash'][:24]+'-ENTRY',trade_id=_trade_id('BULLISH',AT,record['record_hash']),event_type='ENTRY',direction='BULLISH',option_type='CE',transaction_type='BUY',event_timestamp=AT,source_event=event,source_sequence=record['sequence'],source_record_hash=record['record_hash'],strategy_id=SID,decision='WOULD_SUBMIT',reason_code='AUTHORIZED_CURRENT_PRICE_RECOVERY_OCT13',quantity_policy='ONE_DYNAMIC_BROKER_LOT',broker_called=False,sandbox_order_sent=False,live_order_sent=False,observation_only=True,recovery_requested_at=now.isoformat())
            transport=BasketTransport(config.analytics_token,config.sandbox_token)
            try:
                contracts=transport.resolve_five('BULLISH',DAY)
                if len(contracts)!=5 or sorted(c['role'] for c in contracts)!=[-2,-1,0,1,2] or any(c['option_type']!='CE' for c in contracts):raise ValueError('INVALID_CE_BASKET')
                print(json.dumps(dict(mode='EXECUTE' if args.execute else 'PREVIEW',strategy_entry=AT,sandbox_entry='CURRENT_PRICES_AT_SUBMISSION',trade_id=intent['trade_id'],contracts=contracts),indent=2),flush=True)
                if not args.execute:return
                # Revalidate after contract acquisition, immediately before publishing intent.
                active_entry(store.read_all(),datetime.now(IST))
                # Freeze selection via a proxy; normal basket processor owns journals and orders.
                class Frozen:
                    def resolve_five(self,*a):return contracts
                    def __getattr__(self,k):return getattr(transport,k)
                intent_store.append(intent);intents.append(intent)
                worker.process(intent,intents,Frozen(),config)
                print(json.dumps(worker.status('RECOVERY_ATTEMPTED'),indent=2))
                print('Normal serving worker will link subsequent fresh EXIT to this trade. Original audit untouched. Entry prices are current observed quotes, not 09:22 prices.')
            finally:transport.close()
if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Broker exceptions can contain credentials: emit only safe validation errors.
        msg=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else type(exc).__name__
        raise SystemExit('RECOVERY STOPPED: '+msg)
