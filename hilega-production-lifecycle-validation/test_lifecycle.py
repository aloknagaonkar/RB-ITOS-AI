"""Run on the user's VM with installed ownership module; never makes broker calls."""
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('lifecycle_runner',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.mark.parametrize('name',m.SCENARIOS)
def test_composed_lifecycle(tmp_path,name):
    report=m.run_scenario(tmp_path/name,name,m.dependencies())
    assert report['checks']
    assert all(x['status']=='PASS' for x in report['checks'])
    assert report['production_execution_enabled'] is False
    assert report['orders_sent_to_upstox'] is False

def test_transport_requires_reservation(tmp_path):
    s=m.Scenario(tmp_path/'guard',m.dependencies());s.start()
    row=s.adapter.buy('unfunded',instrument='NSE_FO|12345',quantity=65,limit_price='100',signal_at=s.at())
    assert row['status']=='UNKNOWN'
    assert s.store.rows('fake_orders')==[]
    assert s.adapter.status()['control']['mode']=='PAUSED'

def test_changed_request_never_uses_same_reservation(tmp_path):
    s=m.Scenario(tmp_path/'duplicate',m.dependencies());s.start();s.buy()
    with pytest.raises(ValueError,match='NO_RESUBMISSION'):s.buy()
    assert len(s.store.rows('fake_orders'))==1
    assert s.held()=='6600.00'

def test_insufficient_cash_prevents_transport(tmp_path):
    s=m.Scenario(tmp_path/'cap',m.dependencies());s.start()
    # Replace funding by a new, later snapshot. No fill/account activity occurred.
    s.clock[0]+=m.timedelta(seconds=1)
    s.ledger.snapshot('cash-'+s.at(),cash='100',observed_at=s.at(),as_of=s.at(),session_date='2026-10-26')
    with pytest.raises(ValueError,match='HALF_CASH_CAP'):s.buy()
    assert s.store.rows('fake_orders')==[]
    assert s.held()=='0.00'
