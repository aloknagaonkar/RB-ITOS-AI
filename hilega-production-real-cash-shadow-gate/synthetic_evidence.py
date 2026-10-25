"""Explicit synthetic signed capture for offline tests; no real account evidence."""
from market_lab.hilega_production_account_adapter_v1 import sign
AT='2026-10-26T09:25:00+05:30'
PIN=dict(scope='EXPLICIT_SYNTHETIC_ACCOUNT_SCOPE',key='11'*32)

def capture(cash='100000',**changes):
    funds=dict(cash_available_to_trade=cash,field='data.available_to_trade.cash_available_to_trade.total',cash_margin_used='0')
    r=dict(model='HILEGA_READ_ONLY_CASH_OBSERVATION_V1',evidence_mode='LIVE_READ_ONLY_ACCOUNT_PINNED',snapshot_id='sample1',account_scope=PIN['scope'],account_identity_verified=True,status='READ_ONLY_CAPTURED',started_at=AT,completed_at=AT,session_date='2026-10-26',production_execution_enabled=False,orders_sent=False,entry_permission=False,funds_before=funds,funds_after=dict(funds),funds_changed_during_capture=False,orders=[],trades=[],positions=[],diagnostics=dict(issues=[]),account_position_rows_complete=True)
    r.update(changes);r['signature']=sign(r,PIN);return r

