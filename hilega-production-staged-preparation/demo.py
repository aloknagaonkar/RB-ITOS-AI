"""Explicit fixed-date synthetic staging demo; no broker/account access."""
import argparse
import json
from preparation import Preparation, Blocked, FLAGS
from scenarios import build, control


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        port,clock,plan=build(args.output)
        result=port.prepare(**plan)
        checks=[]
        with port.store.db() as db:
            counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in (
                'staged_intents','staged_reservations','staged_adapter_requests','sim_orders','sim_fills')}
        checks.append(dict(check='ATOMIC_INTENT_HOLD_REQUEST',passed=all(counts[t]==1 for t in (
            'staged_intents','staged_reservations','staged_adapter_requests'))))
        checks.append(dict(check='NO_SIMULATOR_ORDERS_OR_FILLS',passed=counts['sim_orders']==counts['sim_fills']==0))
        checks.append(dict(check='ONE_LOT_EXACT_BROKER_FORMAT_KEY',passed=result['quantity']==65 and result['instrument']=='NSE_FO|12345'))
        replay=port.prepare(**plan)
        checks.append(dict(check='DUPLICATE_HISTORICAL_ONLY',passed=replay['historical_only']))
        reopened=Preparation(args.output,clock=lambda:clock[0],reopen=True)
        state=reopened.status()
        checks.append(dict(check='RESTART_PAUSED_HOLD_RETAINED',passed=state['control']['mode']=='PAUSED' and state['staged_held_cents']==660000))
        try:
            control(reopened,'resume');blocked=False
        except Blocked:
            blocked=True
        checks.append(dict(check='UNRESOLVED_STAGE_BLOCKS_RESUME',passed=blocked))
        try:
            reopened.submit(result['id']);blocked=False
        except Blocked:
            blocked=True
        checks.append(dict(check='SUBMISSION_UNCONDITIONALLY_DISABLED',passed=blocked))
        passed=all(x['passed'] for x in checks)
        print(json.dumps(dict(status='PASS' if passed else 'FAIL',evidence_mode='EXPLICIT_STAGED_FIXTURE',
                              checks=checks,counts=counts,**FLAGS)),flush=True)
        return 0 if passed else 2
    except Exception as exc:
        reason=str(exc) if isinstance(exc,Blocked) else 'LOCAL_STAGE_ERROR'
        print(json.dumps(dict(status='BLOCKED',reason=reason,**FLAGS)))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
