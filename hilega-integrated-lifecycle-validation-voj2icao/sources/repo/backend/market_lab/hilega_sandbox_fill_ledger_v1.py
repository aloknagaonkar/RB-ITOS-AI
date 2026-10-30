"""Sandbox-only automatic fill ledger. Old untagged journals retain ACK semantics.

New arms opt into this ledger. Unknown requests are looked up by deterministic
order tag, never resubmitted. Pending cancellations are recorded before calling
Upstox; only terminal provider evidence permits a residual SELL attempt.
"""
from __future__ import annotations
import hashlib, os
from dotenv import dotenv_values
from datetime import datetime
from .hilega_manual_exit_v1 import order_evidence

MODEL = 'HILEGA_SANDBOX_FILL_LEDGER_V1'


def evidence_by_request(rows):
    return {r['request_id']: r['evidence'] for r in rows if r.get('status') == 'ORDER_FILL_VERIFIED'}


def orders(rows):
    return {r['request_id']: r for r in rows if r.get('status') == 'ACCEPTED'
            and r.get('automatic_fill_ledger_version') and not r.get('manual_exit_confirmed')}


def pending_orders(rows):
    evidence = evidence_by_request(rows)
    manually_closed = {(r['trade_id'], r['role']) for r in rows if r.get('manual_exit_confirmed')}
    return [r for rid, r in orders(rows).items()
            if (r['trade_id'], r['role']) not in manually_closed
            and not evidence.get(rid, {}).get('terminal')]


def open_legs(rows):
    opened = {}
    for r in rows:
        if r.get('status') != 'ACCEPTED':
            continue
        key = (r['trade_id'], r['role'])
        if r['event_type'] == 'ENTRY':
            opened[key] = r
        elif r.get('manual_exit_confirmed') or not r.get('automatic_fill_ledger_version'):
            opened.pop(key, None)
    ev = evidence_by_request(rows)
    sells = [r for r in orders(rows).values() if r['event_type'] == 'EXIT']
    result = []
    for key, buy in opened.items():
        if not buy.get('automatic_fill_ledger_version'):
            result.append(buy)
            continue
        bought = ev.get(buy['request_id'])
        sold = sum(ev.get(s['request_id'], {}).get('filled', 0) for s in sells
                   if (s['trade_id'], s['role']) == key)
        if bought and sold > bought['filled']:
            raise ValueError('SELL_QUANTITY_EXCEEDS_FILLED_BUY')
        remaining = bought['filled'] - sold if bought else None
        if bought and bought['terminal'] and remaining == 0:
            continue
        result.append(dict(buy, confirmed_buy=bought, remaining_quantity=remaining))
    return result


def pending_timeout_seconds(worker):
    """Bounded, explicit Sandbox timeout; never disable reconciliation."""
    value = os.getenv('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS')
    if value is None:
        value = dotenv_values(getattr(worker, 'env', '.env')).get('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS', '60')
    try:
        seconds = int(str(value))
    except (ValueError, TypeError):
        raise ValueError('INVALID_SANDBOX_PENDING_TIMEOUT_SECONDS')
    if not 1 <= seconds <= 3600:
        raise ValueError('INVALID_SANDBOX_PENDING_TIMEOUT_SECONDS')
    return seconds


def _cancel_once(worker, tr, order, *, reason='STRATEGY_EXIT_CANCEL_PENDING_BUY', timeout_seconds=None):
    rows = worker.store.rows()
    if any(r.get('status') == 'AUTO_CANCEL_REQUESTED' and r.get('broker_order_id') == order['broker_order_id'] for r in rows):
        return
    worker.store.append(dict(order, status='AUTO_CANCEL_REQUESTED', terminal=False,
                             cancel_reason=reason, pending_timeout_seconds=timeout_seconds,
                             cancel_requested_at=worker.clock().isoformat()))
    try:
        tr.cancel_order(order['broker_order_id'])
    except Exception:
        # Do not interpret a missing cancel response as a terminal order.
        pass


def reconcile_orders(worker, tr):
    timeout = pending_timeout_seconds(worker)
    rows = worker.store.rows()
    for requested in worker.store.uncertain():
        if not requested.get('automatic_fill_ledger_version'):
            continue
        tag = 'HIL5_' + requested['request_id'][:32]
        detail = tr.order_details(tag=tag)
        ev = order_evidence(detail, instrument=requested['contract']['instrument_key'],
                            side=requested['transaction_type'], quantity=requested['quantity'], tag=tag)
        worker.store.append(dict(requested, status='ACCEPTED', terminal=True, broker_order_id=ev['order_id']))
    rows = worker.store.rows()
    previous = evidence_by_request(rows)
    closed = {(r['trade_id'], r['role']) for r in rows if r.get('manual_exit_confirmed')}
    for rid, order in orders(rows).items():
        if (order['trade_id'], order['role']) in closed:
            continue
        old = previous.get(rid)
        if old and old['terminal']:
            continue
        detail = tr.order_details(order_id=order['broker_order_id'])
        ev = order_evidence(detail, instrument=order['contract']['instrument_key'],
                            side=order['transaction_type'], quantity=order['quantity'], order_id=order['broker_order_id'])
        if ev['filled'] < (old or {}).get('filled', 0):
            raise ValueError('BROKER_FILLED_QUANTITY_REGRESSED')
        if old != ev:
            worker.store.append(dict(order, status='ORDER_FILL_VERIFIED', evidence=ev,
                                     verified_at=worker.clock().isoformat(), terminal=ev['terminal']))
        if not ev['terminal'] and (worker.clock() - datetime.fromisoformat(order['timestamp'])).total_seconds() >= timeout:
            _cancel_once(worker, tr, order, reason='PENDING_ORDER_TIMEOUT', timeout_seconds=timeout)
    # Validate aggregate fills before permitting another action.
    worker.store.open_legs()
    c = worker.control.read()
    if c.get('failure_reason') in {'SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED', 'UNCERTAIN_REQUEST_REQUIRES_RECONCILIATION'} and not worker.store.uncertain():
        worker.store.append(dict(status='AUTO_REQUEST_RECONCILED', prior_failure_reason=c['failure_reason']))
        c['entries_blocked'] = False
        c.pop('failure_reason', None)
        c.pop('failed_at', None)
        worker.control.write(c)


def prepare_exit(worker, intent, tr):
    reconcile_orders(worker, tr)
    rows = worker.store.rows()
    buys = [r for r in orders(rows).values() if r['trade_id'] == intent['trade_id'] and r['event_type'] == 'ENTRY']
    ev = evidence_by_request(rows)
    pending = [r for r in buys if not ev.get(r['request_id'], {}).get('terminal')]
    for buy in pending:
        _cancel_once(worker, tr, buy)
    if pending or worker.store.uncertain():
        return False
    if any(r['trade_id'] == intent['trade_id'] and r['event_type'] == 'EXIT' for r in worker.store.pending_fills()):
        return False
    if buys and not any(r['trade_id'] == intent['trade_id'] for r in worker.store.open_legs()) and not any(r['trade_id'] == intent['trade_id'] for r in worker.store.pending_fills()):
        worker.store.append(dict(intent, session_date=worker.control.read()['session_date'],
                                 status='EXIT_NO_POSITION', terminal=True, reason='CONFIRMED_FLAT_OR_UNFILLED_ENTRY'))
        return False
    return True


def submit_exit(worker, intent, base, legs, tr):
    rows = worker.store.rows()
    ev = evidence_by_request(rows)
    for leg in legs:
        prior = [r for r in orders(rows).values() if r['trade_id'] == intent['trade_id']
                 and r['role'] == leg['role'] and r['event_type'] == 'EXIT']
        if any(not ev.get(r['request_id'], {}).get('terminal') for r in prior):
            continue
        if len(prior) >= 3:
            worker.block('AUTO_EXIT_RETRY_LIMIT_RECONCILE_REQUIRED')
            continue
        remaining = leg.get('remaining_quantity')
        if not isinstance(remaining, int) or remaining <= 0:
            worker.block('CONFIRMED_EXIT_QUANTITY_REQUIRED')
            continue
        rid = hashlib.sha256(f"{intent['intent_id']}|{leg['role']}|fill-exit|{len(prior)}".encode()).hexdigest()
        if any(r.get('request_id') == rid for r in rows):
            continue
        request = dict(base, request_id=rid, role=leg['role'], contract=leg['contract'],
                       quantity=remaining, transaction_type='SELL', status='REQUESTED', terminal=False,
                       automatic_fill_ledger_version=MODEL, timestamp=worker.clock().isoformat())
        worker.store.append(request)
        try:
            order_id = tr.place_market(instrument_key=leg['contract']['instrument_key'],
                                       quantity=remaining, transaction_type='SELL', tag='HIL5_' + rid[:32])
        except Exception as exc:
            worker.store.append(dict(request, status='SUBMISSION_UNCERTAIN', error_type=type(exc).__name__))
            worker.block('SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED')
            continue
        worker.store.append(dict(request, status='ACCEPTED', terminal=True, broker_order_id=order_id))
    # Exit intent remains pending until terminal fills prove flat on a later poll.


def apply_fill_pnl(leg, entry, rows):
    if not entry.get('automatic_fill_ledger_version') or leg.get('pnl_basis') == 'CONFIRMED_FILLS':
        return
    ev = evidence_by_request(rows)
    buy = ev.get(entry['request_id'])
    sells = [r for r in orders(rows).values() if r['trade_id'] == entry['trade_id']
             and r['role'] == entry['role'] and r['event_type'] == 'EXIT']
    sold = sum(ev.get(r['request_id'], {}).get('filled', 0) for r in sells)
    proceeds = sum(ev.get(r['request_id'], {}).get('filled', 0) * ev.get(r['request_id'], {}).get('average_price', 0) for r in sells)
    filled = buy['filled'] if buy else 0
    remaining = filled - sold
    if remaining < 0:
        raise ValueError('SELL_QUANTITY_EXCEEDS_FILLED_BUY')
    pending_buy = not buy or not buy['terminal']
    pending_sell = any(not ev.get(r['request_id'], {}).get('terminal') for r in sells)
    terminal = not pending_buy and not pending_sell
    mark = leg.get('current_price')
    cancellations = [r for r in rows if r.get('status') == 'AUTO_CANCEL_REQUESTED'
                     and r.get('request_id') in {entry['request_id'], *(r['request_id'] for r in sells)}]
    leg.update(requested_quantity=entry['quantity'], quantity=filled if buy else None,
               confirmed_filled_quantity=filled if buy else None, remaining_quantity=remaining if buy else None,
               provider_buy_status=buy['status'] if buy else 'AWAITING_ORDER_DETAILS',
               provider_sell_statuses=[ev.get(r['request_id'], {}).get('status', 'AWAITING_ORDER_DETAILS') for r in sells],
               pending_fill=bool(pending_buy or pending_sell),
               cancellation_reason=cancellations[-1].get('cancel_reason', 'RECORDED_CANCELLATION') if cancellations else None,
               sell_order_ids=[r['broker_order_id'] for r in sells],
               fill_verified_at=max((r.get('verified_at','') for r in rows if r.get('status')=='ORDER_FILL_VERIFIED'
                                     and r.get('trade_id')==entry['trade_id'] and r.get('role')==entry['role']), default=None),
               entry_price=buy['average_price'] if filled else None,
               exit_price=proceeds / sold if sold else None,
               points=(mark - buy['average_price']) if remaining and mark is not None else
                      (proceeds / sold - buy['average_price']) if sold and not remaining else None,
               realized_pnl_rupees=proceeds - sold * buy['average_price'] if buy else None,
               pnl_basis='CONFIRMED_FILLS' if terminal and remaining == 0 else 'CONFIRMED_FILLS_AND_MARK_ESTIMATE')
    if terminal and remaining == 0:
        leg.update(status='SELL_FILLED' if filled else 'CANCELLED_UNFILLED',
                   pnl_rupees=proceeds - filled * buy['average_price'], current_price=None)
    else:
        status = ('SELL_PARTIALLY_FILLED' if sold else 'SELL_PENDING_FILL') if pending_sell else (
                 ('BUY_PARTIALLY_FILLED' if filled else 'BUY_PENDING_FILL') if pending_buy else 'BUY_FILLED')
        leg.update(status=status, pnl_rupees=(proceeds - sold * buy['average_price'] +
                   (remaining * (mark - buy['average_price']) if remaining else 0))
                   if filled and (remaining == 0 or mark is not None) else None)


def apply_basket_lifecycle(trade):
    """Display pending orders separately from execution errors; never change worker guards."""
    legs = [leg for leg in trade['legs'] if leg.get('entry_order_id')]
    if not legs or not any(leg.get('pnl_basis', '').startswith('CONFIRMED_FILLS') for leg in legs):
        return
    trade['pending_fill_orders'] = sum(bool(leg.get('pending_fill')) for leg in legs)
    trade['confirmed_open_quantity'] = sum(leg.get('remaining_quantity') or 0 for leg in legs)
    trade['cancelled_unfilled_legs'] = sum(leg['status'] == 'CANCELLED_UNFILLED' for leg in legs)
    if trade['status'] == 'RECONCILIATION_REQUIRED':
        return
    if trade['pending_fill_orders']:
        trade['status'] = 'EXIT_PENDING_FILL' if any(leg['status'].startswith('SELL_') and leg.get('pending_fill') for leg in legs) else 'ENTRY_PENDING_FILL'
    elif trade['confirmed_open_quantity']:
        trade['status'] = 'OPEN_CONFIRMED'
    if not any(leg.get('pnl_rupees') is not None for leg in trade['legs']):
        trade['pnl_rupees'] = None
