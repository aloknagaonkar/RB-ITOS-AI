"""Run an isolated synthetic latch demonstration; accepts no database path."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
from hilega_daily_loss_review_v1 import POLICY
from hilega_daily_loss_latch_v1 import FixtureLatch


def main():
    at=datetime.fromisoformat('2026-10-29T11:00:00+05:30')
    scope='FIXTURE:DEMO'
    config=dict(account_scope=scope,session_date='2026-10-29',loss_accounting_policy=POLICY,
        policy_approved=True,daily_loss_limit_paise=100000,max_entry_cost_paise=50000,max_pnl_age_seconds=30)
    evidence=dict(account_scope=scope,session_date='2026-10-29',pnl_attribution_verified=True,
        fees_complete=True,positions_reconciled=True,requests_reconciled=True,daily_stop_latched=False,
        open_position_count=0,pending_request_count=0,unresolved_outcome=False,observed_at=at.isoformat(),
        realized_net_pnl_paise=-100000,open_net_pnl_paise=0)
    candidate=dict(account_scope=scope,session_date='2026-10-29',transaction_type='BUY',instrument_type='CE',
        pricing_policy_approved=True,cost_includes_fees=True,max_loss_cost_paise=20000)
    with tempfile.TemporaryDirectory(prefix='hilega-loss-latch-FIXTURE-') as directory:
        path=Path(directory)/'fixture.sqlite'
        store=FixtureLatch.create(path);store.initialize(config,as_of=at)
        trip=store.record(config,evidence,candidate,as_of=at,request_id='demo-trip')
        assert trip['current_durable_stop_latched'] is True
        reopened=FixtureLatch(path)
        assert reopened.state(scope)['latched'] is True
        recovered=deepcopy(evidence);recovered['realized_net_pnl_paise']=20000
        result=reopened.record(config,recovered,candidate,as_of=at,request_id='demo-recovered')
        assert result['status']=='BLOCKED' and result['entry_permission'] is False
        tomorrow=at+timedelta(days=1)
        new_config=dict(config,session_date='2026-10-30')
        closure=dict(account_scope=scope,previous_session_date='2026-10-29',previous_session_reconciled=True,
            positions_reconciled=True,requests_reconciled=True,fees_complete=True,open_position_count=0,
            pending_request_count=0,unresolved_outcome=False,observed_at=tomorrow.isoformat())
        new=reopened.rollover(new_config,closure,as_of=tomorrow)
        assert new['latched'] is False and new['session_date']=='2026-10-30'
    print(json.dumps(dict(status='ISOLATED_LATCH_DEMO_PASS',scope='FIXTURE_ONLY',
        committed_trip_survives_reopen=True,recovered_pnl_does_not_clear_stop=True,
        explicit_fixture_rollover_demonstrated=True,temporary_database_removed=True,
        live_pnl_authenticated=False,runtime_integration=False,entry_permission=False,
        production_execution_enabled=False,orders_sent=False,production_ready=False),indent=2))

if __name__=='__main__':main()
