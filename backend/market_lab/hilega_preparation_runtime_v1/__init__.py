"""Application preparation route. No real order transport or release authority."""
import json
import os
from .evidence import FLAGS


def route():
    value=os.getenv('HILEGA_PRODUCTION_EXECUTION_ROUTE','SIMULATOR')
    if value not in {'SIMULATOR','PREPARATION_ONLY'}:
        raise ValueError('UNSUPPORTED_EXECUTION_ROUTE')
    return value


def pending(store):
    with store.db() as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return 'preparation_plans' in tables and db.execute('SELECT 1 FROM preparation_plans LIMIT 1').fetchone() is not None


def ensure_route(store):
    """Called under installed control flock; enrollment cannot be removed by env."""
    selected=route()
    with store.db() as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        old=db.execute('SELECT data FROM preparation_route WHERE id=1').fetchone() if 'preparation_route' in tables else None
        if old:
            if json.loads(old[0])!={'route':selected,'model':'APPLICATION_PREPARATION_ROUTE_V1'}:
                raise ValueError('PERSISTED_EXECUTION_ROUTE_MISMATCH')
        elif selected=='PREPARATION_ONLY':
            if any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in (
                'intents','sim_orders','sim_fills','sim_allocation_reservations')):
                raise ValueError('SIMULATOR_EXECUTION_HISTORY_CANNOT_MIX_WITH_PREPARATION_ROUTE')
            db.execute('CREATE TABLE preparation_route(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('INSERT INTO preparation_route VALUES(1,?)',(json.dumps(dict(route=selected,model='APPLICATION_PREPARATION_ROUTE_V1')),))


def summary(store):
    selected=route()
    with store.db() as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        plans=db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0] if 'preparation_plans' in tables else 0
        held=0
        if 'preparation_shadow_holds' in tables:
            held=sum(json.loads(r[0])['held_cents'] for r in db.execute('SELECT data FROM preparation_shadow_holds'))
        latest=db.execute('SELECT data FROM preparation_events ORDER BY seq DESC LIMIT 1').fetchone() if 'preparation_events' in tables else None
    return dict(FLAGS,route=selected,application_signal_route_integrated=True,
                unresolved_preparation_count=plans,shadow_held_cents=held,
                last_outcome=json.loads(latest[0]) if latest else None,
                submission_gate='CLOSED_IN_CODE',real_cash_reservation_integrated=False,
                note='Unsent evidence-bound plans; no executable price policy, broker orders or real fills')
