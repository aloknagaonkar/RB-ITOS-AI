"""Read local position/intent ledgers only. Never constructs a transport."""
import json
from pathlib import Path

def probe():
    from market_lab.hilega_upstox_sandbox_basket_v2 import BasketStore, JOURNAL
    from market_lab.hilega_upstox_sandbox_live_worker_v1 import DispatchStore, DEFAULT_DISPATCH
    from market_lab.hilega_upstox_sandbox_execution_v1 import JsonlJournal, SandboxConfig
    store=BasketStore(JOURNAL)
    legacy=DispatchStore(DEFAULT_DISPATCH).rows();opened=set()
    for r in legacy:
        if r.get('status')=='ACCEPTED':
            if r['event_type']=='ENTRY':opened.add(r['trade_id'])
            else:opened.discard(r['trade_id'])
    # Config construction reads local settings only; no readiness/transport call.
    historical=JsonlJournal(SandboxConfig.from_env(Path('.env')).journal_path).rows()
    terminal={r.get('event_id') for r in historical if r.get('terminal')}
    manual=JOURNAL.parent/'manual-exit.json'
    pending_manual=0
    if manual.exists():pending_manual=sum(r.get('status')!='READY_FOR_FRESH_SIGNAL' for r in json.loads(manual.read_text()).get('requests',[]))
    result=dict(open_legs=len(store.open_legs()),pending_fill_orders=len(store.pending_fills()),
        uncertain_requests=len(store.uncertain()),legacy_open_trades=len(opened),
        legacy_failed_requests=sum(r.get('status')=='FAILED' and not r.get('terminal') for r in legacy),
        legacy_uncertain_requests=sum(r.get('status')=='REQUESTED' and r.get('event_id') not in terminal for r in historical),
        pending_manual_exits=pending_manual)
    return dict(status='LOCAL_LEDGERS_FLAT' if not any(result.values()) else 'BLOCKED_EXISTING_POSITIONS_OR_REQUESTS',
                counts=result,broker_requests_sent=False,broker_account_reconciled=False)
if __name__=='__main__':print(json.dumps(probe()))
