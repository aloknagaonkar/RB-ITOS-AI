"""Only isolated synthetic controller/adapter scenarios; installed classes reused."""
from pathlib import Path
from datetime import datetime,timedelta
import json,uuid
from market_lab.hilega_production_foundation.core import Service,Store,SimBroker
from market_lab.hilega_sim_allocation_v1 import synthetic_funds
from link import Link,load_adapter
AT='2026-10-26T09:25:00+05:30'

def command(s,action):
    c=s.status()['control'];return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='ISOLATED_LINK_VALIDATION')
def build(path,*,closed=False):
    path=Path(path);path.mkdir(parents=True,mode=0o700)
    db=path/'controller-simulation.sqlite'
    (path/'ISOLATED_LINK_VALIDATION.json').write_text(json.dumps(dict(controller_db=str(db.resolve()),purpose='ISOLATED_CONTROLLER_ADAPTER_VALIDATION')))
    clock=[datetime.fromisoformat(AT)-timedelta(seconds=1)];store=Store(db);broker=SimBroker(store);service=Service(store,broker,lambda:clock[0])
    synthetic_funds(service,'100000');command(service,'reconcile');command(service,'resume');clock[0]=datetime.fromisoformat(AT)
    modules=load_adapter();m,mapping=modules;adapter_store=m.Store(path/'adapter.sqlite','EXPLICIT_ISOLATED_SCOPE','LIVE_CLOSED' if closed else 'OFFLINE_FIXTURE')
    transport=m.HttpTransport(lambda:(_ for _ in ()).throw(AssertionError('TOKEN_ACCESS_FORBIDDEN'))) if closed else m.FixtureTransport(adapter_store)
    adapter=m.Adapter(adapter_store,transport);link=Link(service,adapter,modules)
    # Prepare via actual public entry checks, stopping precisely after the installed
    # atomic reservation/intent transaction, before SimBroker transport.
    original=service._submit
    class Prepared(BaseException):pass
    def stop(row):raise Prepared()
    service._submit=stop
    try:service.submit_entry(signal_id='fixture-fresh',signal_at=AT,instrument='SIMULATOR|CE',quantity=65,price='100')
    except Prepared:pass
    finally:service._submit=original
    entry=store.intents()[0]
    contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    return service,broker,clock,link,entry,contract
