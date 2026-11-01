"""Regression scenarios for VM execution. No provider or order connections."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from market_lab import hilega_sandbox_fill_ledger_v1 as ledger

AT = datetime.fromisoformat('2026-10-15T10:00:00+05:30')


def order(kind='ENTRY', rid='buy', quantity=65):
    return dict(request_id=rid, intent_id=kind, event_id=kind, trade_id='trade', role=0,
                direction='BULLISH', session_date='2026-10-15', strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',
                source_sequence=10, event_timestamp=AT.isoformat(), timestamp=AT.isoformat(),
                event_type=kind, transaction_type='BUY' if kind=='ENTRY' else 'SELL',
                contract=dict(instrument_key='NSE_FO|123', role=0), quantity=quantity,
                broker_order_id=rid, status='ACCEPTED', terminal=True,
                automatic_fill_ledger_version=ledger.MODEL)


def evidence(row, filled=0, status='open pending', price=100):
    return dict(row, status='ORDER_FILL_VERIFIED', verified_at=AT.isoformat(),
                evidence=dict(order_id=row['broker_order_id'], status=status, filled=filled,
                              pending=row['quantity']-filled if status=='open pending' else 0,
                              average_price=price if filled else 0,
                              terminal=status in {'complete','cancelled','rejected'}))


def leg_for(buy, rows, mark=110):
    leg=dict(entry_order_id=buy['broker_order_id'], current_price=mark, status='BUY_ACKNOWLEDGED')
    ledger.apply_fill_pnl(leg,buy,rows)
    return leg


def test_pending_ack_has_no_invented_position_pnl():
    buy=order();leg=leg_for(buy,[buy,evidence(buy)])
    assert leg['status']=='BUY_PENDING_FILL' and leg['quantity']==0
    assert leg['entry_price'] is None and leg['pnl_rupees'] is None
    trade=dict(legs=[leg],status='OPEN_ACKNOWLEDGED',pnl_rupees=0)
    ledger.apply_basket_lifecycle(trade)
    assert trade['status']=='ENTRY_PENDING_FILL' and trade['pnl_rupees'] is None


def test_confirmed_open_fill_has_points_and_mark_pnl():
    buy=order();leg=leg_for(buy,[buy,evidence(buy,65,'complete')])
    assert leg['status']=='BUY_FILLED' and leg['points']==10 and leg['pnl_rupees']==650
    trade=dict(legs=[leg],status='OPEN_ACKNOWLEDGED')
    ledger.apply_basket_lifecycle(trade)
    assert trade['status']=='OPEN_CONFIRMED' and trade['confirmed_open_quantity']==65


def test_zero_fill_cancelled_order_has_no_position():
    buy=order();cancel=dict(buy,status='AUTO_CANCEL_REQUESTED',cancel_reason='PENDING_ORDER_TIMEOUT')
    leg=leg_for(buy,[buy,cancel,evidence(buy,0,'cancelled')])
    assert leg['status']=='CANCELLED_UNFILLED' and leg['pnl_rupees']==0
    assert leg['current_price'] is None and leg['entry_price'] is None
    assert leg['cancellation_reason']=='PENDING_ORDER_TIMEOUT'


def test_pending_partial_sell_retains_residual_mark_pnl():
    buy=order();sell=order('EXIT','sell')
    leg=leg_for(buy,[buy,evidence(buy,65,'complete'),sell,evidence(sell,20,'open pending',105)],mark=110)
    assert leg['status']=='SELL_PARTIALLY_FILLED' and leg['remaining_quantity']==45
    assert leg['realized_pnl_rupees']==100 and leg['pnl_rupees']==550
    trade=dict(legs=[leg],status='CLOSED_ACKNOWLEDGED')
    ledger.apply_basket_lifecycle(trade)
    assert trade['status']=='EXIT_PENDING_FILL'


def test_real_uncertain_request_is_not_hidden_by_pending_status():
    buy=order();leg=leg_for(buy,[buy,evidence(buy)])
    trade=dict(legs=[leg],status='RECONCILIATION_REQUIRED')
    ledger.apply_basket_lifecycle(trade)
    assert trade['status']=='RECONCILIATION_REQUIRED'


def test_completed_sell_uses_fill_prices_not_current_quote():
    buy=order();sell=order('EXIT','sell')
    leg=leg_for(buy,[buy,evidence(buy,65,'complete'),sell,evidence(sell,65,'complete',105)],mark=200)
    assert leg['status']=='SELL_FILLED' and leg['points']==5 and leg['pnl_rupees']==325


@pytest.mark.parametrize('value',['0','-1','3601','abc','1.5'])
def test_invalid_timeout_is_rejected(monkeypatch,value):
    monkeypatch.setenv('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS',value)
    with pytest.raises(ValueError,match='INVALID_SANDBOX_PENDING_TIMEOUT'):
        ledger.pending_timeout_seconds(SimpleNamespace())


def test_timeout_reads_env_file_and_keeps_default(tmp_path,monkeypatch):
    monkeypatch.delenv('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS',raising=False)
    worker=SimpleNamespace(env=tmp_path/'.env')
    assert ledger.pending_timeout_seconds(worker)==60
    worker.env.write_text('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS=120\n')
    assert ledger.pending_timeout_seconds(worker)==120
    monkeypatch.setenv('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS','180')
    assert ledger.pending_timeout_seconds(worker)==180


def test_cancel_timeout_is_audited_once_and_not_a_fill(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_SANDBOX_PENDING_TIMEOUT_SECONDS','120')
    buy=order();rows=[buy];control={};current=[AT+timedelta(seconds=90)];cancels=[]
    store=SimpleNamespace(rows=lambda:list(rows),append=rows.append,uncertain=lambda:[],open_legs=lambda:ledger.open_legs(rows))
    worker=SimpleNamespace(store=store,control=SimpleNamespace(read=lambda:dict(control),write=control.update),clock=lambda:current[0],env=tmp_path/'.env')
    detail=dict(order_id='buy',instrument_token='NSE_FO|123',transaction_type='BUY',product='I',
                quantity=65,filled_quantity=0,pending_quantity=65,status='open pending',average_price=0)
    provider=SimpleNamespace(order_details=lambda **kwargs:detail,cancel_order=cancels.append)
    ledger.reconcile_orders(worker,provider)
    assert not cancels
    current[0]=AT+timedelta(seconds=121)
    ledger.reconcile_orders(worker,provider);ledger.reconcile_orders(worker,provider)
    assert cancels==['buy']
    cancellation=next(r for r in rows if r['status']=='AUTO_CANCEL_REQUESTED')
    assert cancellation['cancel_reason']=='PENDING_ORDER_TIMEOUT' and cancellation['pending_timeout_seconds']==120
    assert len(ledger.pending_orders(rows))==1  # Cancel ACK cannot prove terminal state.


def test_legacy_quote_pnl_is_preserved():
    buy=order();buy.pop('automatic_fill_ledger_version')
    leg=dict(pnl_rupees=650,status='BUY_ACKNOWLEDGED')
    ledger.apply_fill_pnl(leg,buy,[buy])
    assert leg==dict(pnl_rupees=650,status='BUY_ACKNOWLEDGED')
