"""Synthetic example of missing production risk inputs; no VM/account access."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo
from hilega_daily_loss_review_v1 import review, POLICY

now=datetime.now(ZoneInfo('Asia/Kolkata'))
common=dict(account_scope='OFFLINE_EXAMPLE_ONLY',session_date=now.date().isoformat())
result=review(
    dict(common,loss_accounting_policy=POLICY,policy_approved=False,
         daily_loss_limit_paise=None,max_entry_cost_paise=None,max_pnl_age_seconds=None),
    dict(common,pnl_attribution_verified=False,fees_complete=False,
         positions_reconciled=False,requests_reconciled=False,daily_stop_latched=None,
         open_position_count=None,pending_request_count=None,unresolved_outcome=None,
         observed_at=None,realized_net_pnl_paise=None,open_net_pnl_paise=None),
    dict(common,transaction_type='BUY',instrument_type='CE',pricing_policy_approved=False,
         cost_includes_fees=False,max_loss_cost_paise=None),
    as_of=now,expected_account_scope=common['account_scope'],
)
assert result['status']=='BLOCKED'
assert result['entry_permission'] is False
print(json.dumps(result,indent=2))
