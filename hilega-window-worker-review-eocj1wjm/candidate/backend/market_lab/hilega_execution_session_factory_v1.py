"""Explicit candidate session factory. No environment activation or credential-file loader."""


def need(ok,reason):
    if not ok:raise ValueError(reason)


def closed():
    return dict(status='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE',factory_context_loaded=False,
        account_capture_requested=False,entry_permission=False,orders_sent_to_upstox=False,
        production_execution_enabled=False,production_ready=False)


class ExecutionSessionFactory:
    def __init__(self,context_loader):
        need(callable(context_loader),'EXPLICIT_CONTEXT_LOADER_REQUIRED')
        self._loader=context_loader;self._cached=None;self._source=None;self._journal=None

    def poll(self,source,journal):
        from market_lab.hilega_execution_port_v1 import adapter as port
        # This installed gate is always closed. It precedes context/authority/provider reads.
        try:port.require_live_clearance()
        except port.GateClosed:return closed()
        from pathlib import Path
        from closed_application_coordinator_v1 import CandidateSession
        from market_lab.hilega_exclusive_closed_route_v1 import candidate_poll
        resolved=Path(journal).resolve()
        if self._cached is None:
            value=self._loader()
            required={'adapter','pin','authority','seed_request_id','bridge_run_id','providers','clock'}
            need(type(value) is dict and required<=set(value)<=required|{'checkpoint'},'EXACT_FACTORY_CONTEXT_REQUIRED')
            need(value['bridge_run_id']==source.run_id,'FACTORY_SOURCE_LEASE_CHANGED')
            session=CandidateSession(source.s.store,value['adapter'],source,value['pin'],value['authority'],
                journal=resolved,seed_request_id=value['seed_request_id'],bridge_run_id=value['bridge_run_id'],
                providers=value['providers'],clock=value['clock'],checkpoint=value.get('checkpoint',lambda at:None))
            session._runtime()
            self._cached=session;self._source=source;self._journal=resolved
        need(source is self._source and resolved==self._journal,'FACTORY_SOURCE_OR_JOURNAL_CHANGED')
        # Existing signed owner must verify. No implicit enrollment or new seed adoption.
        return candidate_poll(self._cached)


def worker_poll(bridge,journal,*,factory=None):
    if factory is None:
        from market_lab.hilega_exclusive_closed_route_v1 import closed_poll
        return closed_poll(bridge,journal)
    need(type(factory) is ExecutionSessionFactory,'EXACT_EXECUTION_SESSION_FACTORY_REQUIRED')
    return factory.poll(bridge,journal)
