from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from market_lab import hilega_sandbox_fill_ledger_v1 as ledger
from market_lab.hilega_upstox_sandbox_basket_v2 import BasketWorker

AT = datetime.fromisoformat('2026-10-14T12:00:00+05:30')


def order(kind='ENTRY', rid='buy', quantity=65):
    return dict(request_id=rid, intent_id=kind, event_id=kind, trade_id='trade', role=0,
                direction='BULLISH', session_date='2026-10-14', strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
                source_sequence=10, event_timestamp=AT.isoformat(), timestamp=AT.isoformat(),
                event_type=kind, transaction_type='BUY' if kind=='ENTRY' else 'SELL',
                contract=dict(instrument_key='NSE_FO|123', role=0, strike=22500, option_type='CE', lot_size=65, expiry='2026-10-19'),
                quantity=quantity, broker_order_id=rid, status='ACCEPTED', terminal=True,
                automatic_fill_ledger_version=ledger.MODEL)


def detail(row, *, filled, status='complete', price=100):
    return dict(order_id=row['broker_order_id'], instrument_token=row['contract']['instrument_key'],
                transaction_type=row['transaction_type'], product='I', quantity=row['quantity'],
                filled_quantity=filled, pending_quantity=0 if status in {'complete','cancelled','rejected'} else row['quantity']-filled,
                status=status, average_price=price if filled else 0)


class Provider:
    def __init__(self, details): self.details=details; self.calls=[]; self.cancels=[]
    def order_details(self, *, order_id=None, tag=None):
        if order_id is None: raise LookupError('unknown tag')
        return self.details[order_id]
    def cancel_order(self, order_id): self.cancels.append(order_id)
    def place_market(self, **kw): self.calls.append(kw); return 'sell'+str(len(self.calls))


def worker(tmp_path):
    w=BasketWorker(control=tmp_path/'control.json', journal=tmp_path/'events.jsonl', clock=lambda:AT)
    w.control.write(dict(session_date='2026-10-14', automatic_fill_ledger_version=ledger.MODEL))
    return w


def test_ack_is_pending_not_confirmed_fill(tmp_path):
    w=worker(tmp_path); buy=order(); w.store.append(buy)
    assert w.store.open_legs()[0]['remaining_quantity'] is None
    assert len(w.store.pending_fills())==1
    p=Provider({'buy':detail(buy,filled=0,status='open pending')})
    ledger.reconcile_orders(w,p)
    assert w.store.open_legs()[0]['remaining_quantity']==0
    assert len(w.store.pending_fills())==1


def test_cancelled_partial_buy_sells_only_filled_quantity(tmp_path):
    w=worker(tmp_path); buy=order(); w.store.append(buy)
    p=Provider({'buy':detail(buy,filled=20,status='cancelled')})
    ledger.reconcile_orders(w,p)
    intent=order('EXIT','exit')
    assert ledger.prepare_exit(w,intent,p)
    ledger.submit_exit(w,intent,intent,w.store.open_legs(),p)
    assert p.calls[0]['quantity']==20
    p.details['sell1']=detail(order('EXIT','sell1',20),filled=20,price=110)
    ledger.reconcile_orders(w,p)
    assert w.store.open_legs()==[]
    leg=dict(current_price=115)
    ledger.apply_fill_pnl(leg,buy,w.store.rows())
    assert leg['pnl_rupees']==200 and leg['status']=='SELL_FILLED'


def test_pending_buy_cancel_is_durable_once_and_exit_waits(tmp_path):
    w=worker(tmp_path); buy=order(); w.store.append(buy)
    p=Provider({'buy':detail(buy,filled=10,status='open pending')})
    assert not ledger.prepare_exit(w,order('EXIT','exit'),p)
    assert not ledger.prepare_exit(w,order('EXIT','exit'),p)
    assert p.cancels==['buy'] and not p.calls


def test_zero_filled_terminal_buy_becomes_harmless_exit(tmp_path):
    w=worker(tmp_path); buy=order(); w.store.append(buy)
    p=Provider({'buy':detail(buy,filled=0,status='rejected')})
    intent=order('EXIT','exit')
    assert not ledger.prepare_exit(w,intent,p)
    assert w.store.rows()[-1]['status']=='EXIT_NO_POSITION' and not p.calls


def test_partial_sell_retry_is_residual_and_pending_sell_not_repeated(tmp_path):
    w=worker(tmp_path); buy=order(); w.store.append(buy)
    p=Provider({'buy':detail(buy,filled=65)})
    ledger.reconcile_orders(w,p); intent=order('EXIT','exit')
    ledger.submit_exit(w,intent,intent,w.store.open_legs(),p)
    p.details['sell1']=detail(order('EXIT','sell1'),filled=20,status='open pending',price=110)
    ledger.reconcile_orders(w,p)
    assert not ledger.prepare_exit(w,intent,p)
    assert len(p.calls)==1
    p.details['sell1']=detail(order('EXIT','sell1'),filled=20,status='cancelled',price=110)
    ledger.reconcile_orders(w,p)
    ledger.submit_exit(w,intent,intent,w.store.open_legs(),p)
    assert p.calls[-1]['quantity']==45


def test_identity_mismatch_and_fill_regression_are_blocked(tmp_path):
    w=worker(tmp_path); buy=order(); w.store.append(buy)
    p=Provider({'buy':detail(buy,filled=10,status='open pending')})
    ledger.reconcile_orders(w,p)
    p.details['buy']['filled_quantity']=5
    with pytest.raises(ValueError,match='REGRESSED'): ledger.reconcile_orders(w,p)
    p.details['buy']['instrument_token']='other'
    with pytest.raises(ValueError,match='IDENTITY'): ledger.reconcile_orders(w,p)


def test_legacy_ack_journal_retains_interpretation(tmp_path):
    w=worker(tmp_path); buy=order(); buy.pop('automatic_fill_ledger_version'); w.store.append(buy)
    assert w.store.open_legs()[0]['quantity']==65 and not w.store.pending_fills()


def test_unknown_buy_is_recovered_by_tag_without_resubmission(tmp_path):
    w=worker(tmp_path);buy=order();requested=dict(buy,status='REQUESTED',terminal=False)
    requested.pop('broker_order_id');w.store.append(requested)
    c=w.control.read();c.update(entries_blocked=True,failure_reason='SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED');w.control.write(c)
    p=Provider({'buy':detail(buy,filled=65)})
    real=p.order_details;lookups=[]
    def details(*,order_id=None,tag=None):
        if tag:
            lookups.append(tag)
            return dict(p.details['buy'],tag=tag)
        return real(order_id=order_id)
    p.order_details=details
    ledger.reconcile_orders(w,p);ledger.reconcile_orders(w,p)
    assert lookups==['HIL5_buy'] and not p.calls
    assert len(w.store.accepted())==1 and not w.store.uncertain()
    assert w.control.read()['entries_blocked'] is False


def test_aggregate_oversell_evidence_is_rejected(tmp_path):
    w=worker(tmp_path);buy=order();sell=order('EXIT','sell',80)
    w.store.append(buy);w.store.append(sell)
    p=Provider({'buy':detail(buy,filled=65),'sell':detail(sell,filled=80)})
    with pytest.raises(ValueError,match='EXCEEDS_FILLED_BUY'):ledger.reconcile_orders(w,p)
