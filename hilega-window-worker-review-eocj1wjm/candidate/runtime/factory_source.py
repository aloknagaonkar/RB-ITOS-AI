"""Adapt an actual Bridge to one stable guarded preparation Source after the gate."""
from pathlib import Path
from authority_contract import need


def prepare_factory_source(worker,bridge,journal):
    from market_lab.hilega_execution_port_v1 import adapter as port
    # A test may override this in memory; installed production bytes stay closed.
    port.require_live_clearance()
    from market_lab.hilega_preparation_runtime_v1.source import Source
    from market_lab.hilega_production_simulator_bridge_v1 import Bridge
    from market_lab.hilega_exclusive_closed_route_v1 import _guarded_source
    need(type(bridge) in {Source,Bridge},'EXACT_FACTORY_BRIDGE_REQUIRED')
    if type(bridge) is Source:
        _guarded_source(bridge);return bridge
    cached=getattr(worker,'_prepared_source',None)
    if cached is not None:
        need(worker._input_bridge is bridge,'FACTORY_INPUT_BRIDGE_CHANGED')
        need(cached.s is bridge.s and cached.run_id==bridge.run_id,'FACTORY_SOURCE_LEASE_CHANGED')
        need(worker._input_journal==Path(journal).resolve(),'FACTORY_INPUT_JOURNAL_CHANGED')
        _guarded_source(cached);return cached
    # Do not let Source's CREATE IF NOT EXISTS provision missing preparation
    # tables as a side effect of execution-factory attachment.
    with bridge.s.store.db() as db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need({'preparation_source','preparation_events','preparation_consumed','preparation_evidence',
              'preparation_plans','preparation_shadow_holds','preparation_outbox',
              'preparation_request_bindings','preparation_cash_reservations',
              'preparation_candidate_exclusive_source_owner_v1'}<=tables,'EXISTING_FACTORY_PREPARATION_REQUIRED')
        cursor=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()
        need(cursor is not None,'EXISTING_FACTORY_CURSOR_REQUIRED')
    def forbidden():raise AssertionError('No automatic bootstrap evidence capture')
    source=Source(bridge.s,run_id=bridge.run_id,provider=forbidden);_guarded_source(source)
    worker._prepared_source=source;worker._input_bridge=bridge;worker._input_journal=Path(journal).resolve()
    return source
