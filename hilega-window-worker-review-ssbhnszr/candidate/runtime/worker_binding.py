"""Explicit disabled-by-default worker registration and pause-before-attachment recovery."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
from authority_contract import need,digest,verify,binding
from authority_files import private_bytes,trust_roots,grant_file
from factory_adapter import AuthorityBoundFactory,pause_for_recovery

FIELDS={'model','enabled','expected_binding','private_config_file','private_config_sha256','trust_registry_file','trust_registry_sha256','grant_file','grant_sha256','production_execution_enabled'}


def registration(path,expected):
    value=json.loads(private_bytes(path,expected))
    need(type(value) is dict and set(value)==FIELDS and value['model']=='HILEGA_WORKER_AUTHORITY_REGISTRATION_CANDIDATE_V1'
         and type(value['enabled']) is bool and value['production_execution_enabled'] is False,'EXACT_CLOSED_AUTHORITY_REGISTRATION_REQUIRED')
    if not value['enabled']:
        need(all(value[k] is None for k in FIELDS-{'model','enabled','production_execution_enabled'}),'DISABLED_REGISTRATION_MUST_HAVE_NO_PRIVATE_BINDINGS')
    else:
        binding(value['expected_binding'])
        need(value['private_config_sha256']==value['expected_binding']['private_context_sha256'],'PRIVATE_CONFIG_BINDING_CHANGED')
    return value


def ensure_paused(service):
    if service.store.control()['mode']=='PAUSED' and not service.store.stop_state()['pending']:
        return dict(status='EXISTING_PAUSED_BASELINE_VERIFIED',controller_resumed=False)
    return pause_for_recovery(service)


class RegisteredAuthorityWorker:
    def __init__(self,path,expected_sha256,*,clock=lambda:datetime.now(timezone.utc)):
        self.path,self.expected,self.clock=Path(path),expected_sha256,clock
        self.factory=None;self.source=None;self.journal=None;self.startup_checked=False

    def poll(self,source,journal):
        from market_lab.hilega_execution_session_factory_v1 import worker_poll,closed
        value=registration(self.path,self.expected)
        if not value['enabled']:return worker_poll(source,journal)
        need(hasattr(source,'s') and hasattr(source.s,'store'),'APPLICATION_SOURCE_REQUIRED')
        if not self.startup_checked:
            ensure_paused(source.s);self.startup_checked=True
        from market_lab.hilega_execution_port_v1 import adapter as port
        try:port.require_live_clearance()
        except port.GateClosed:return closed()
        try:
            from factory_source import prepare_factory_source
            source=prepare_factory_source(self,source,journal)
            bind=value['expected_binding']
            roots=lambda:trust_roots(value['trust_registry_file'],value['trust_registry_sha256'],bind)
            grants=lambda:grant_file(value['grant_file'],value['grant_sha256'])
            verify(grants(),bind,roots(),self.clock())
            if self.factory is None:
                config=json.loads(private_bytes(value['private_config_file'],value['private_config_sha256']))
                path=Path(config['adapter_db'])
                # The canonical Store may only reopen an existing, complete store;
                # no missing database/table is silently provisioned by registration.
                need(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),'EXISTING_ADAPTER_DATABASE_REQUIRED')
                need(Path(config['application_db']).resolve()==source.s.store.path.resolve() and Path(config['journal']).resolve()==Path(journal).resolve(),'EXACT_APPLICATION_AND_JOURNAL_REQUIRED')
                with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                    db.execute('PRAGMA query_only=ON')
                    names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    need({'meta','requests','attempts','receipts','events','fixture_orders'}<=names,'COMPLETE_EXISTING_ADAPTER_SCHEMA_REQUIRED')
                    meta=json.loads(db.execute('SELECT data FROM meta WHERE id=1').fetchone()[0])
                    need(meta==dict(scope=bind['account_scope'],mode='LIVE_CLOSED'),'EXISTING_ADAPTER_SCOPE_CHANGED')
                store=port.Store(path,bind['account_scope'],'LIVE_CLOSED')
                from market_lab.hilega_private_context_v1 import PrivateContextLoader
                loader=PrivateContextLoader(source,store,journal,value['private_config_file'],value['private_config_sha256'],clock=self.clock)
                self.factory=AuthorityBoundFactory(loader,expected_binding=bind,grant_loader=grants,trust_loader=roots,clock=self.clock)
                self.source,self.journal=source,Path(journal).resolve()
            need(source is self.source and Path(journal).resolve()==self.journal,'REGISTERED_WORKER_SOURCE_OR_JOURNAL_CHANGED')
            return self.factory.poll(source,journal)
        except Exception:
            ensure_paused(source.s)
            raise


_DEFAULT=None
def _default_worker_poll_without_window(source,journal):
    from factory_attachment import attachment_poll
    attached=attachment_poll(source,journal)
    if attached is not None:return attached
    from bootstrap_worker import configured_poll
    local_result=configured_poll(source,journal)
    if local_result is not None:return local_result
    global _DEFAULT
    root=Path(__file__).absolute().parent.parent
    manifest=json.loads((root/'RELEASE-MANIFEST.json').read_text())
    path=root/'runtime/FACTORY-REGISTRATION.json';expected=manifest['files']['runtime/FACTORY-REGISTRATION.json']
    if _DEFAULT is None:_DEFAULT=RegisteredAuthorityWorker(path,expected)
    need(_DEFAULT.path==path and _DEFAULT.expected==expected,'WORKER_REGISTRATION_CHANGED')
    return poll_with_journal_health(_DEFAULT,source,journal)


def poll_with_journal_health(worker,source,journal):
    """Read-only source time for the outer worker heartbeat; no cursor mutation."""
    from market_lab.hilega_production_simulator_bridge_v1 import verified_records,POLICY,VERSION
    from market_lab.hilega_production_bridge_health_v1 import source_timestamp
    records=verified_records(journal)
    source_at=source_timestamp(records,POLICY,VERSION)
    value=worker.poll(source,journal)
    need(isinstance(value,dict),'REGISTERED_WORKER_RESULT_REQUIRED')
    # Never replace a stale/missing source time with the process clock.
    return dict(value,source_at=source_at)


def default_worker_poll(source,journal):
    from window_worker_bridge import before_poll
    if not before_poll(source,journal):
        return dict(status='WINDOW_GUARD_REJECTED_PAUSED',production_execution_enabled=False)
    result=_default_worker_poll_without_window(source,journal)
    from window_worker_bridge import observe
    return observe(source,journal,result)
