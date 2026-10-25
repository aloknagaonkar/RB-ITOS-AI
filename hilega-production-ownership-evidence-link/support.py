"""Explicit offline snapshots: fill rows are supplied separately, never inferred."""
import importlib.util,sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def dependencies():
    expected=json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for rel,fp in expected.items():
        p=ROOT/rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=fp:raise ValueError('DEPENDENCY_CHANGED_'+rel)
    folder=ROOT/'hilega-production-controller-adapter-link'
    sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location('installed_link_fixtures',folder/'fixtures.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def snapshot(adapter,*,sid,at,trades):
    orders=[];positions={}
    for o in adapter.transport.orders():
        orders.append(dict(order_id=o['order_id'],instrument=o['instrument'],product=o['product'],side=o['side'],quantity=o['quantity'],filled=o['filled'],pending=0 if o['status'] in {'FILLED','CANCELLED','REJECTED'} else o['quantity']-o['filled'],status=o['status']))
        k=(o['instrument'],o['product']);positions[k]=positions.get(k,0)+(o['filled'] if o['side']=='BUY' else -o['filled'])
    return dict(evidence_mode='OFFLINE_FIXTURE',account_scope=adapter.store.scope,snapshot_id=sid,observed_at=at,complete=True,orders=orders,trades=trades,positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])

def fill(oid,side,quantity,*,at,trade_id):return dict(order_id=oid,trade_id=trade_id,instrument='NSE_FO|12345',product='I',side=side,quantity=quantity,price='100',filled_at=at)

def prepare_fixture_exit(controller_link,request_id,quantity,*,at):
    # Explicit fixture-only partial cleanup; this is not an approved production
    # partial-lot request constructor or execution authorization.
    from provider_mapping import draft
    contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    r=draft(contract,request_id=request_id,side='SELL',lots=1,as_of=at);r['body']['quantity']=quantity;r['fingerprint']=controller_link.module.sha(r['body'])
    controller_link.adapter.prepare(r,signal_id=request_id,signal_at=at,direction='BULLISH',reservation_reference='EXPLICIT_OFFLINE_EXIT_REFERENCE',as_of=at)
    return r
