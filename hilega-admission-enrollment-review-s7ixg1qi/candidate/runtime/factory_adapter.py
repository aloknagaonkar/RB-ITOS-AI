"""Candidate authority gate + existing private loader/factory + native pause recovery."""
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid
from authority_contract import binding,verify,need,digest


def pause_for_recovery(service):
    """Uses the existing monotonic native pause path; never reads private context."""
    c=service.store.control()
    service.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],
                    actor='CANDIDATE_AUTHORITY_RECOVERY',session_date=c['session_date'])
    need(service.store.control()['mode']=='PAUSED' and not service.store.stop_state()['pending'],'AUTHORITY_RECOVERY_PAUSE_FAILED')
    return dict(status='CANDIDATE_NATIVE_PAUSE_RECOVERY_PASS',controller_paused=True,
                controller_resumed=False,orders_sent=False,production_execution_enabled=False)


class AuthorityBoundFactory:
    def __init__(self,private_loader,*,expected_binding,grant_loader,trust_loader,clock):
        self.loader=private_loader;self.expected=binding(expected_binding)
        need(all(callable(v) for v in (grant_loader,trust_loader,clock)),'EXPLICIT_AUTHORITY_PROVIDERS_REQUIRED')
        self.grant_loader,self.trust_loader,self.clock=grant_loader,trust_loader,clock
        self._factory=None;self._source=None;self._journal=None

    def poll(self,source,journal):
        from market_lab.hilega_execution_port_v1 import adapter as port
        from market_lab.hilega_execution_session_factory_v1 import closed,ExecutionSessionFactory
        # This check is intentionally before grant/trust/private file providers.
        try:port.require_live_clearance()
        except port.GateClosed:return closed()
        try:
            from market_lab.hilega_private_context_v1 import PrivateContextLoader,private_read
            need(type(self.loader) is PrivateContextLoader,'EXACT_PRIVATE_CONTEXT_LOADER_REQUIRED')
            need(self.loader.source is source and str(source.run_id)==self.expected['bridge_run_id'],'AUTHORITY_SOURCE_LEASE_CHANGED')
            resolved=Path(journal).resolve()
            need(Path(self.loader.journal).resolve()==resolved and self.loader.expected==self.expected['private_context_sha256'],'AUTHORITY_PRIVATE_CONTEXT_CHANGED')
            if self._factory is not None:
                need(source is self._source and resolved==self._journal,'AUTHORITY_CACHED_SOURCE_OR_JOURNAL_CHANGED')
            # Revalidate the grant, current trust registry, private files and signed
            # owner on every poll, including cached-session and restart paths.
            roots=self.trust_loader();grant=self.grant_loader()
            approval=verify(grant,self.expected,roots,self.clock())
            context=self.loader()
            need(context['pin']['scope']==self.expected['account_scope'] and context['authority']['authority_id']==self.expected['authority_id']
                 and digest(bytes.fromhex(context['authority']['key']))==self.expected['authority_key_sha256']
                 and context['seed_request_id']==self.expected['seed_request_id'] and context['bridge_run_id']==self.expected['bridge_run_id'], 'PRIVATE_AUTHORITY_CONTEXT_BINDING_CHANGED')
            # The signing root must not be the account-capture key either.
            need(approval['issuer_key_sha256']!=digest(bytes.fromhex(context['pin']['key'])),'CAPTURE_KEY_CANNOT_ISSUE_AUTHORITY_GRANT')
            config=json.loads(private_read(self.loader.config_path))
            need(approval['issuer_key_sha256']!=config['broker_token_sha256'],'BROKER_TOKEN_CANNOT_ISSUE_AUTHORITY_GRANT')
            from market_lab.hilega_exclusive_closed_route_v1 import TABLE
            with sqlite3.connect(source.s.store.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                db.execute('PRAGMA query_only=ON')
                row=db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()
            need(row is not None and digest(row[0].encode())==self.expected['owner_row_sha256'],'AUTHORITY_SIGNED_OWNER_CHANGED')
            if self._factory is None:
                self._factory=ExecutionSessionFactory(lambda:context);self._source=source;self._journal=resolved
            return self._factory.poll(source,journal)
        except Exception:
            # Any admitted-session validation failure requires pause and review,
            # never a new authority, implicit enrollment, resubmission or resume.
            pause_for_recovery(source.s)
            raise
