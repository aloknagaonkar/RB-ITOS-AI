import json
from pathlib import Path
import sqlite3
import pytest
from hilega_position_policy_v1 import occupied, enforce, validate_policy


def entry(key,side='BUY',state='PREPARED'):
    return (key,dict(request_id=key,state=state,draft=dict(body=dict(transaction_type=side,quantity=1))))


def test_one_entry_has_no_monetary_caps():
    r=occupied([entry('a')],set(),'a',1)
    assert r['occupied_position_slots']==1 and not r['premium_cap_configured'] and not r['daily_loss_cutoff_configured']


@pytest.mark.parametrize('state',['PREPARED','IN_FLIGHT','UNKNOWN','PARTIAL','FILLED','CANCELLED','REJECTED'])
def test_unretired_entry_blocks_another_even_if_state_changes(state):
    with pytest.raises(ValueError,match='MAX_SIMULTANEOUS'):
        occupied([entry('a',state=state),entry('b')],set(),'b',1)


def test_sell_is_part_of_existing_position_not_another_slot():
    assert occupied([entry('a'),entry('exit','SELL')],set(),'a',1)['occupied_position_slots']==1


def test_retirement_exclusion_allows_next_entry():
    assert occupied([entry('a'),entry('b')],{'a'},'b',1)['occupied_position_slots']==1


def test_explicit_future_limit_can_be_four():
    assert occupied([entry(str(i)) for i in range(4)],set(),'3',4)['occupied_position_slots']==4


def test_boolean_capacity_rejected():
    with pytest.raises(ValueError):occupied([entry('a')],set(),'a',True)


def test_enforce_requires_account_scope_and_unfiltered_requests(tmp_path):
    db=sqlite3.connect(':memory:');db.execute("ATTACH DATABASE ':memory:' AS broker")
    db.execute('CREATE TABLE broker.meta(id INTEGER PRIMARY KEY,data TEXT)')
    db.execute('CREATE TABLE broker.requests(id TEXT PRIMARY KEY,data TEXT)')
    db.execute('INSERT INTO broker.meta VALUES(1,?)',(json.dumps(dict(scope='synthetic',mode='LIVE_CLOSED')),))
    for key,row in [entry('a'),entry('b')]:db.execute('INSERT INTO broker.requests VALUES(?,?)',(key,json.dumps(row)))
    class Projection:
        raw=db
        def execute(self,*args):raise AssertionError('Projected request reads must not hide other entries')
    with pytest.raises(ValueError,match='MAX_SIMULTANEOUS'):enforce(Projection(),dict(scope='synthetic'),'b')
    with pytest.raises(ValueError,match='ACCOUNT_SCOPE'):enforce(Projection(),dict(scope='other'),'b')
    db.close()


def test_null_caps_are_exact_user_configuration():
    policy=json.loads(Path(__file__).with_name('POSITION-POLICY.json').read_text())
    assert validate_policy(policy)==1
    policy['max_premium_per_entry_cents']=100
    with pytest.raises(ValueError,match='MONETARY_LIMITS'):validate_policy(policy)
