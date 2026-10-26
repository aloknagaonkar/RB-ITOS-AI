"""Explicit synthetic setup for VM tests/demo; not a real-account data source."""
import uuid
from datetime import datetime, timedelta
from preparation import Preparation
from market_lab import hilega_production_bridge_health_v1 as health
from market_lab import hilega_sim_allocation_v1 as allocation

AT = datetime.fromisoformat('2026-10-26T09:25:00+05:30')


def control(port, action):
    current = port.store.control()
    return port.command(action,request_id=str(uuid.uuid4()),actor='ISOLATED_STAGE_VALIDATION',
                        expected_version=current['version'],session_date=current['session_date'])


def build(directory):
    clock = [AT-timedelta(seconds=1)]
    port = Preparation(directory,clock=lambda:clock[0])
    allocation.synthetic_funds(port._service,'100000')
    run = health.claim(port._service)
    health.heartbeat(port._service,run,source_at=clock[0].isoformat())
    control(port,'reconcile')
    control(port,'resume')
    clock[0] = AT
    c = port.store.control()
    plan = dict(signal_id='synthetic-signal',signal_at=AT.isoformat(),direction='BULLISH',
        contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',
            instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,
            minimum_lot=65,freeze_quantity=1800),contract_at=AT.isoformat(),
        quote=dict(instrument='NSE_FO|12345',at=AT.isoformat(),bid='99.95',ask='100',
                   tick_rupees='0.05',evidence_mode='EXPLICIT_STAGED_FIXTURE'),
        expected_version=c['version'],session_date=c['session_date'],bridge_run_id=run)
    return port,clock,plan
