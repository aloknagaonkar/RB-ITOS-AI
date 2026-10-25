"""Run on the VM; packaged module is isolated from installed market_lab."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('observation_view', Path(__file__).resolve().parents[1] / 'files/backend/market_lab/hilega_strike_observation_ui_v1.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


def frame(**updates):
    row = dict(instrument_key='CE1', entry_ask=100, quantity=65, total_cost_rupees=10, current_bid=110,
               quote_timestamp=NOW.isoformat(), price_evidence_source='MARKET_UPDATE',
               audit={'selection_reason': 'Highest modelled ROI', 'favourable_conditions': ['Delta in band']})
    row.update(updates)
    return dict(model=m.MODEL, max_quote_age_seconds=5, top5=[row])


def test_missing_journal(tmp_path):
    assert m.dashboard(tmp_path/'absent', NOW)['status'] == 'NOT_CONNECTED'


def test_fresh_net_pnl_preserves_audit():
    r = m.project(frame(), NOW)['top5'][0]
    assert r['points'] == 10 and r['pnl_rupees'] == 640
    assert r['audit']['selection_reason'] == 'Highest modelled ROI'


def test_stale_quote_not_used():
    r = m.project(frame(quote_timestamp='2026-10-14T09:59:00+00:00'), NOW)['top5'][0]
    assert r['pnl_rupees'] is None


def test_response_timestamp_not_market_evidence():
    assert m.project(frame(price_evidence_source='PROVIDER_RESPONSE_TIMESTAMP'), NOW)['top5'][0]['pnl_rupees'] is None


def test_cost_and_quantity_missing_not_zero_filled():
    for fields in ({'total_cost_rupees': None}, {'quantity': None}, {'quantity': 1.5}):
        assert m.project(frame(**fields), NOW)['top5'][0]['pnl_rupees'] is None


def test_closed_historical_exit_retains_pnl():
    r = m.project(frame(state='CLOSED', exit_bid=90, exit_quote_timestamp='2026-10-13T10:00:00+00:00'), NOW)['top5'][0]
    assert r['pnl_rupees'] == -660 and r['pnl_status'] == 'CLOSED_HYPOTHETICAL'


def test_partial_write_and_corrupt_frame(tmp_path):
    p = tmp_path/'journal'
    p.write_text(json.dumps(frame())+'\ninvalid\n'+json.dumps(frame()))
    data = m.dashboard(p, NOW)
    assert len(data['frames']) == 1 and data['errors'] == ['INVALID_OBSERVATION_FRAME']


def test_duplicate_contract_rejected():
    f = frame(); f['top5'] *= 2
    try:
        m.project(f, NOW)
    except ValueError as e:
        assert str(e) == 'INVALID_SELECTED_IDENTITIES'
    else:
        raise AssertionError('duplicate identity accepted')
