"""Isolated, one-lot Upstox Sandbox fill probe. Run only on the VM.

No strategy intents, control files or worker journals are changed. Durable
state prevents a second BUY on rerun. Never interpret an ACK as a fill.
"""
import argparse
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from filelock import FileLock
from market_lab.hilega_upstox_sandbox_execution_v1 import SandboxConfig
from market_lab.hilega_upstox_sandbox_basket_v2 import BasketTransport
from market_lab.hilega_manual_exit_v1 import order_evidence

ROOT = Path('data/research/hilega-sandbox-demo-lifecycle-v2')
IST = ZoneInfo('Asia/Kolkata')


def stamp():
    return datetime.now(IST).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', required=True, choices=['SANDBOX_ONLY'])
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    cfg = SandboxConfig.from_env('.env')
    if not cfg.enabled or cfg.kill_switch:
        raise SystemExit('Sandbox must be enabled with its kill switch OFF')
    if not cfg.analytics_token or not cfg.sandbox_token:
        raise SystemExit('Analytics and Sandbox tokens are required')
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'state.json'
    with FileLock(str(ROOT / 'demo.lock'), timeout=0):
        if path.exists() and not args.resume:
            raise SystemExit('Existing demo state found. Use --resume; do not delete it to retry.')
        if args.resume and not path.exists():
            raise SystemExit('No demo state to resume')
        state = json.loads(path.read_text()) if path.exists() else dict(id=uuid.uuid4().hex[:18], started_at=stamp())

        def persist():
            temporary = path.with_suffix('.tmp')
            with temporary.open('w') as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)

        def log(kind, **data):
            row = dict(timestamp=stamp(), demo_id=state['id'], kind=kind, **data)
            with (ROOT / 'events.jsonl').open('a') as f:
                f.write(json.dumps(row) + '\n')
                f.flush()
                os.fsync(f.fileno())
            print(json.dumps(row), flush=True)

        if state.get('done'):
            print(json.dumps(state, indent=2))
            return
        tr = BasketTransport(cfg.analytics_token, cfg.sandbox_token)
        try:
            # A literal host check prevents accidentally using a live broker.
            if str(tr.sandbox.base_url).rstrip('/') != 'https://api-sandbox.upstox.com':
                raise ValueError('SANDBOX_HOST_REQUIRED')
            if 'contract' not in state:
                # Verify that the earlier isolated demo remains terminal and unfilled.
                previous = tr.order_details(order_id='261015100515116')
                prior = order_evidence(previous, instrument='NSE_FO|47155', side='BUY',
                                       quantity=65, order_id='261015100515116')
                log('PREVIOUS_DEMO_VERIFIED', **prior)
                if not prior['terminal'] or prior['filled'] != 0:
                    raise ValueError('PREVIOUS_DEMO_REQUIRES_RECONCILIATION_NO_NEW_BUY')
            if 'contract' not in state:
                if args.resume:
                    raise ValueError('INCOMPLETE_INITIALIZATION_NO_ORDERS_SENT')
                day = datetime.now(IST).date().isoformat()
                candidates = tr.resolve_five('BULLISH', day)
                contract = next(c for c in candidates if c['role'] == 0)
                state['contract'] = contract
                state['quantity'] = int(contract['lot_size'])
                if state['quantity'] <= 0:
                    raise ValueError('INVALID_LOT_SIZE')
                persist()
                log('DEMO_CONTRACT', contract=contract, quantity=state['quantity'])

            def submit(side, quantity):
                slot = side.lower()
                existing = state.get(slot)
                if existing:
                    if not existing.get('order_id'):
                        raise ValueError('SUBMISSION_UNCERTAIN: inspect provider history for tag ' + existing['tag'] + '; do not resubmit')
                    return existing
                tag = 'HILDEMO_' + state['id'] + '_' + side
                order = dict(tag=tag, quantity=quantity, submitted_at=stamp())
                state[slot] = order
                persist()  # Record intent before the network request.
                body = dict(quantity=quantity, product='I', validity='DAY', price=0,
                            tag=tag, instrument_token=state['contract']['instrument_key'],
                            order_type='MARKET', transaction_type=side, disclosed_quantity=0,
                            trigger_price=0, is_amo=False, slice=False, market_protection=-1)
                log('SUBMIT', side=side, payload=body)
                response = tr._body(tr.sandbox.post('/v3/order/place', json=body))
                ids = (response.get('data') or {}).get('order_ids') or []
                if len(ids) != 1:
                    raise ValueError('AMBIGUOUS_ORDER_RESPONSE: inspect provider by saved tag')
                order['order_id'] = str(ids[0])
                persist()
                log('ACKNOWLEDGED', side=side, order_id=order['order_id'])
                return order

            def monitor(side, order):
                deadline = time.monotonic() + 120
                while True:
                    detail = tr.order_details(order_id=order['order_id'])
                    ev = order_evidence(detail, instrument=state['contract']['instrument_key'],
                                        side=side, quantity=order['quantity'], order_id=order['order_id'])
                    if ev['filled'] < order.get('evidence', {}).get('filled', 0):
                        raise ValueError('FILLED_QUANTITY_REGRESSED')
                    order['evidence'] = ev
                    persist()
                    log('ORDER_EVIDENCE', side=side, **ev)
                    if ev['terminal']:
                        return ev
                    if time.monotonic() >= deadline:
                        if not order.get('cancel_requested_at'):
                            order['cancel_requested_at'] = stamp()
                            persist()
                            log('TIMEOUT_CANCEL_REQUEST', side=side, order_id=order['order_id'])
                            tr.cancel_order(order['order_id'])
                            # A cancel ACK is not a terminal order. Allow bounded reconciliation.
                            deadline = time.monotonic() + 30
                        else:
                            raise ValueError('ORDER_NOT_TERMINAL: run --resume; do not submit another demo')
                    time.sleep(5)

            buy = monitor('BUY', submit('BUY', state['quantity']))
            if buy['filled'] == 0:
                state.update(done=True, verdict='ACCEPTED_BUT_NO_FILL', pnl_rupees=0)
                persist()
                log('RESULT', verdict=state['verdict'], filled=0, pnl_rupees=0)
                return
            sell = monitor('SELL', submit('SELL', buy['filled']))
            remaining = buy['filled'] - sell['filled']
            if remaining != 0:
                state['remaining_quantity'] = remaining
                persist()
                raise ValueError('DEMO_RESIDUAL_POSITION: ' + str(remaining) + ' units; inspect saved state, no automatic duplicate SELL')
            pnl = sell['filled'] * (sell['average_price'] - buy['average_price'])
            state.update(done=True, verdict='BUY_AND_SELL_FILLS_VERIFIED', pnl_rupees=pnl)
            persist()
            log('RESULT', verdict=state['verdict'], pnl_rupees=pnl, costs_included=False)
        except Exception as exc:
            log('STOPPED_RECONCILIATION_REQUIRED', error_type=type(exc).__name__, error=str(exc))
            raise SystemExit(1)
        finally:
            tr.close()


if __name__ == '__main__':
    main()
