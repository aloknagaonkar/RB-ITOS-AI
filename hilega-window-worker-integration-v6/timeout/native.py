"""Native controller adapter restricted to newly created disposable rehearsal state."""
import json,os,sys
from pathlib import Path
from window import need

def service(bundle,workspace):
    workspace=Path(workspace).resolve();marker=workspace/'DISPOSABLE-WINDOW.json'
    need(marker.is_file() and not marker.is_symlink(),'DISPOSABLE_MARKER_REQUIRED')
    info=json.loads(marker.read_text());need(info==dict(model='HILEGA_DISPOSABLE_WINDOW_V1',workspace=str(workspace)),'EXACT_DISPOSABLE_WORKSPACE_REQUIRED')
    app=workspace/'application.sqlite'
    need(app.is_file() and not any(p.is_symlink() for p in [app,*app.parents]),'EXISTING_DISPOSABLE_DATABASE_REQUIRED')
    os.environ['HILEGA_PRODUCTION_EXECUTION_ROUTE']='PREPARATION_ONLY'
    os.environ['HILEGA_PRODUCTION_WORKSPACE_MODE']='SIMULATION_ONLY'
    sys.dont_write_bytecode=True;sys.path[:0]=[str(Path(bundle)/'backend'),str(Path(bundle)/'runtime')]
    from market_lab.hilega_production_foundation.core import Store,SimBroker,Service
    from market_lab.hilega_execution_port_v1.adapter import require_live_clearance,GateClosed
    try:require_live_clearance()
    except GateClosed:pass
    else:raise ValueError('HARD_ORDER_GATE_NOT_CLOSED')
    store=Store(app);return Service(store,SimBroker(store),worker_start=False)
