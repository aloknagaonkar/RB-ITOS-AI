"""Isolated offline composition of tested adapters; no broker transport or app writes."""
import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load(name, relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def dependencies():
    expected = json.loads((Path(__file__).parent / 'dependencies.json').read_text())
    for relative, fingerprint in expected.items():
        path = ROOT / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
            raise ValueError('DEPENDENCY_MISSING_OR_CHANGED: ' + relative)
    mapping = load('provider_mapping', 'hilega-production-intent-binding/provider_mapping.py')
    registry = load('lifecycle_registry', 'hilega-production-intent-binding/registry.py')
    adapter = load('lifecycle_adapter', 'hilega-production-order-adapter-contract/adapter.py')
    allocation = load('lifecycle_allocation', 'hilega-production-allocation-reservations/ledger.py')
    return mapping, registry, adapter, allocation

class Scenario:
    def __init__(self, path, modules):
        self.path = path
        path.mkdir(mode=0o700)
        self.mapping, self.reg, self.mod, self.alloc = modules
        self.clock = [datetime.fromisoformat('2026-10-26T09:24:59+05:30')]
        self.store = self.mod.Store(path / 'fake.sqlite')
        self.transport = self.mod.FakeTransport(self.store, lambda: self.clock[0])
        self.adapter = self.mod.Adapter(self.store, self.transport, lambda: self.clock[0])
        self.registry = self.reg.Registry(path / 'binding.sqlite', 'OFFLINE_ACCOUNT', 'OFFLINE_FIXTURE')
        self.ledger = self.alloc.Ledger(path / 'allocation.sqlite', 'OFFLINE_ACCOUNT')
        self.transport.before_place = self.before_place
        self.rows = []
        self.fail_at = None
        self.fund()

    def at(self): return self.clock[0].isoformat()
    def fund(self):
        self.ledger.snapshot('cash-' + self.at(), cash='100000', observed_at=self.at(), as_of=self.at(), session_date='2026-10-26')
    def held(self): return self.ledger.status()['held_total']
    def check(self, label, condition):
        self.rows.append(dict(check=label, status='PASS' if condition else 'FAIL', held=self.held(), control=self.adapter.status()['control']['mode'], fake_orders=len(self.store.rows('fake_orders'))))
        if not condition: raise AssertionError(label)

    def before_place(self, row):
        # Runs before FakeTransport inserts an order. A crash here cannot POST.
        if row['side'] == 'BUY' and not any(r['id'] == row['request_id'] and r['held_cents'] > 0 for r in self.ledger.status()['reservations']):
            raise ValueError('RESERVATION_REQUIRED_BEFORE_FAKE_ORDER')
        contract = dict(instrument_key=row['instrument'], underlying_key='NSE_INDEX|Nifty 50', instrument_type='CE', segment='NSE_FO', expiry='2026-10-27', lot_size=65, minimum_lot=65, freeze_quantity=1800)
        request = self.mapping.draft(contract, request_id=row['request_id'], side=row['side'], lots=1, as_of=self.at())
        # Synthetic cleanup can sell fewer than one lot after a partial BUY.
        # This is NOT a validated production partial-exit request builder.
        request['body']['quantity'] = row['quantity']
        request['fingerprint'] = self.reg.sha(request['body'])
        self.registry.prepare(request, signal_id=row['request_id'], signal_at=row.get('signal_at', self.at()), direction='BULLISH', parent_id=row['parent'])
        if self.fail_at == 'AFTER_INTENT': raise RuntimeError('INJECTED_STOP_AFTER_DURABLE_INTENT')

    def buy(self, key='entry'):
        old = next((r for r in self.ledger.status()['reservations'] if r['id'] == key), None)
        if old: raise ValueError('CONSUMED_OR_UNRESOLVED_PLAN_NO_RESUBMISSION')
        if self.adapter.status()['control']['mode'] != 'ARMED': raise ValueError('PAUSED')
        # This runner serializes all actions. It is not a multi-process controller.
        if any(r['held_cents'] for r in self.ledger.status()['reservations']): raise ValueError('EXISTING_HOLD')
        legs = [dict(instrument='NSE_FO|12345', side='CE', offset=0, lot_size=65, lots=1, quantity=65, ask='100', buffer='100')]
        self.ledger.reserve(key, signal_id=key, snapshot_id='cash-' + self.at(), legs=legs, as_of=self.at(), session_date='2026-10-26')
        if self.fail_at == 'AFTER_RESERVE': raise RuntimeError('INJECTED_STOP_AFTER_RESERVATION')
        return self.adapter.buy(key, instrument='NSE_FO|12345', quantity=65, limit_price='100', signal_at=self.at())

    def sync(self):
        self.adapter.reconcile()
        snap = self.transport.snapshot()
        intents = self.store.rows('intents')
        for row in intents:
            oid = row.get('order_id')
            if not oid: raise ValueError('UNRESOLVED_ACK')
            # Fake reference matching is fixture evidence, never live provenance.
            self.registry.bind_fixture_ack(row['request_id'], 'fixture-' + oid, dict(status='success', data=dict(order_ids=[oid])), at=self.at())
        orders = [{k:v for k,v in o.items() if k not in {'client_reference','account_scope'}} for o in snap['orders']]
        by_order = {r['order_id']:r for r in intents}
        bound = {r['intent_id']:r for r in self.registry._rows()}
        trades = [dict(f, filled_at=bound[by_order[f['order_id']]['request_id']]['request']['created_at']) for f in snap['fills']]
        proof = dict(evidence_mode='OFFLINE_FIXTURE', account_scope='OFFLINE_ACCOUNT', complete=True, snapshot_id='generation-' + str(snap['generation']), observed_at=self.at(), orders=orders, trades=trades, positions=snap['positions'])
        # Repeated polls use the same evidence object in this driver.
        proof['snapshot_id'] += '-' + self.at()
        result = self.registry.reconcile_fixture(proof, as_of=self.at())
        if result['status'] not in {'RECONCILED_OFFLINE_FIXTURE','IDEMPOTENT_REPLAY'}: raise ValueError('OWNERSHIP_NOT_RECONCILED: ' + result['status'])
        for hold in self.ledger.status()['reservations']:
            if hold['state'] == 'RELEASED': continue
            entry = next((r for r in intents if r['request_id'] == hold['id']), None)
            if entry is None: continue # orphan hold is retained for review
            related = [r for r in intents if r['request_id'] == hold['id'] or r.get('parent') == hold['id']]
            remaining = entry['filled'] - sum(r['filled'] for r in related if r['side'] == 'SELL')
            terminal = all(r['status'] in self.mod.TERMINAL for r in related)
            if terminal and remaining == 0:
                self.ledger.evidence('release-' + hold['id'], hold['id'], state='RELEASED', as_of=self.at(), terminal_no_exposure=True)
        return result

    def start(self):
        self.adapter.resume()
        self.clock[0] += timedelta(seconds=1)
        self.fund()
    def restart(self):
        self.adapter = self.mod.Adapter(self.store, self.transport, lambda: self.clock[0])
        self.registry = self.reg.Registry(self.path / 'binding.sqlite', 'OFFLINE_ACCOUNT', 'OFFLINE_FIXTURE')
        self.ledger = self.alloc.Ledger(self.path / 'allocation.sqlite', 'OFFLINE_ACCOUNT')
    def report(self):
        return dict(checks=self.rows, adapter=self.adapter.status(), allocation=self.ledger.status(), binding=self.registry.status(as_of=self.at()), evidence_mode='OFFLINE_FIXTURE', production_execution_enabled=False, orders_sent_to_upstox=False)

def run_scenario(path, name, modules):
    s = Scenario(path, modules)
    s.start()
    if name in {'AFTER_RESERVE','AFTER_INTENT'}:
        s.fail_at = name
        try: s.buy()
        except RuntimeError: pass
        s.check('Interrupted preparation retains full hold; no venue order', s.held()=='6600.00' and len(s.store.rows('fake_orders'))==0)
        s.restart()
        s.check('Restart stays paused and retains orphan/unknown hold', s.adapter.status()['control']['mode']=='PAUSED' and s.held()=='6600.00')
        try: s.adapter.resume()
        except Exception: pass
        try: s.buy()
        except ValueError: pass
        s.check('Consumed reservation never automatically resubmits', len(s.store.rows('fake_orders'))==0 and s.held()=='6600.00')
    elif name == 'ACCEPTANCE_UNKNOWN':
        s.transport.timeout_after_accept=True
        row=s.buy()
        s.check('Accepted timeout pauses and holds cash', row['status']=='UNKNOWN' and s.held()=='6600.00' and s.adapter.status()['control']['mode']=='PAUSED')
        s.restart()
        s.sync()
        s.check('Fixture reconciliation binds original order without another BUY', len(s.store.rows('fake_orders'))==1 and s.held()=='6600.00')
        s.adapter.pause();s.sync()
        s.check('Verified zero-fill cancellation releases hold', s.held()=='0.00')
    elif name == 'PARTIAL_CANCEL':
        row=s.buy();s.transport.fill(row['order_id'],20,'100');s.sync()
        s.check('Partial entry retains full hold', s.held()=='6600.00')
        s.transport.auto_sell_fill=False
        s.adapter.pause();s.sync()
        s.check('Cleanup SELL pending retains hold', s.held()=='6600.00')
        sell=next(o for o in s.store.rows('fake_orders') if o['side']=='SELL')
        s.transport.fill(sell['order_id'],20,'100');s.sync()
        s.check('Cleanup fill and terminal flat evidence release hold', s.held()=='0.00')
    else:
        row=s.buy();s.transport.fill(row['order_id'],65,'100');s.sync()
        s.adapter.pause();s.sync()
        s.check('Pause retains established exposure and allocation', s.held()=='6600.00' and len(s.store.rows('fake_orders'))==1)
        s.restart();s.sync()
        s.check('Restart remains paused with established hold', s.held()=='6600.00' and s.adapter.status()['control']['mode']=='PAUSED')
        s.transport.auto_sell_fill=False
        sell=s.adapter.exit('entry');s.sync()
        s.check('Manual exit pending retains hold', s.held()=='6600.00')
        s.transport.fill(sell['order_id'],65,'105');s.sync();s.sync()
        s.check('Completed exit releases once; repeated evidence creates no order', s.held()=='0.00' and len(s.store.rows('fake_orders'))==2)
    return s.report()

SCENARIOS = ['AFTER_RESERVE','AFTER_INTENT','ACCEPTANCE_UNKNOWN','PARTIAL_CANCEL','ESTABLISHED_EXIT']
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists(): raise ValueError('USE_FRESH_OUTPUT_DIRECTORY')
    modules=dependencies();a.output.mkdir(parents=True,mode=0o700)
    reports={};failed=False
    for name in SCENARIOS:
        print('CHECK: '+name,flush=True)
        try:
            result=run_scenario(a.output/name,name,modules)
            reports[name]=result
        except Exception as exc:
            reports[name]=dict(status='FAIL',error=type(exc).__name__,reason=str(exc));failed=True
        (a.output/name/'report.json').write_text(json.dumps(reports[name],indent=2))
    text='# Integrated offline lifecycle validation\n\nSynthetic cash, orders, acknowledgement provenance and execution times. Single serialized runner; no production integration.\n\n| Scenario | Check | Result | Held INR |\n|---|---|---|---:|\n'
    for name,r in reports.items():
        for c in r.get('checks',[]):text+=f"| {name} | {c['check']} | {c['status']} | {c['held']} |\n"
        if r.get('status')=='FAIL':text+=f"| {name} | {r['reason']} | FAIL | — |\n"
    status='FAIL' if failed else 'PASS';text+='\nOverall: '+status+'\nProduction execution enabled: false. No Upstox requests.\n'
    (a.output/'summary.md').write_text(text)
    (a.output/'report.json').write_text(json.dumps(dict(status=status,scenarios=reports,production_execution_enabled=False,orders_sent_to_upstox=False),indent=2))
    print(text);return 2 if failed else 0
if __name__=='__main__':raise SystemExit(main())
