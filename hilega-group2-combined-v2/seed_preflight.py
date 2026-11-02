"""Fail early with the actual synthetic seed-block reason, before dependent fixture indexing."""
import json
from test_hilega_application_preparation_v1 import env,process
from test_hilega_atomic_disabled_binding_v1 import bound_env

def test_staged_dependency_chain_allows_one_disabled_seed(bound_env):
    e=bound_env
    process(e)
    rows=e['adapter_store'].requests()
    with e['store'].db() as db:
        row=db.execute('SELECT data FROM preparation_events ORDER BY seq DESC LIMIT 1').fetchone()
        value=json.loads(row[0]) if row else {}
    safe={k:value.get(k) for k in ('status','reasons')}
    assert len(rows)==1, {'synthetic_seed_not_created':safe}
    assert rows[0]['state']=='PREPARED' and rows[0]['order_id'] is None
    assert e['store'].control()['mode']=='PAUSED'
    with e['adapter_store'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==0
