"""Pinned external registration attachment, disabled unless explicitly configured and gated."""
import json,os
from pathlib import Path
from authority_contract import need,digest,aware,canonical

FIELDS={'model','release_sha256','policy_sha256','application_db','journal','bridge_run_id',
        'registration_file','registration_sha256','expected_binding_sha256','issued_at','expires_at','production_execution_enabled'}
_WORKER=None
_REFERENCE=None
_SOURCE=None
_JOURNAL=None
_STARTED=False


def journal_time(journal):
    from market_lab.hilega_production_simulator_bridge_v1 import verified_records,POLICY,VERSION
    from market_lab.hilega_production_bridge_health_v1 import source_timestamp
    return source_timestamp(verified_records(journal),POLICY,VERSION)


def descriptor(path,expected,source,journal,now):
    from authority_files import private_bytes
    value=json.loads(private_bytes(path,expected))
    need(type(value) is dict and set(value)==FIELDS and value['model']=='HILEGA_PINNED_FACTORY_ATTACHMENT_CANDIDATE_V1'
         and value['production_execution_enabled'] is False,'EXACT_CLOSED_FACTORY_ATTACHMENT_REQUIRED')
    root=Path(__file__).absolute().parent.parent
    need(digest((root/'RELEASE-MANIFEST.json').read_bytes())==value['release_sha256'],'ATTACHMENT_RELEASE_CHANGED')
    need(digest((root/'runtime/POSITION-POLICY.json').read_bytes())==value['policy_sha256'],'ATTACHMENT_POLICY_CHANGED')
    need(value['application_db']==str(source.s.store.path.resolve()) and value['journal']==str(Path(journal).resolve()),'ATTACHMENT_APPLICATION_OR_JOURNAL_CHANGED')
    need(value['bridge_run_id']==source.run_id,'ATTACHMENT_SOURCE_LEASE_CHANGED')
    start,end=aware(value['issued_at']),aware(value['expires_at'])
    need(0<(end-start).total_seconds()<=3600 and start<=now<end,'ATTACHMENT_EXPIRED_OR_FUTURE')
    return value


def attachment_poll(source,journal):
    global _WORKER,_REFERENCE,_SOURCE,_JOURNAL,_STARTED
    path=os.environ.get('HILEGA_FACTORY_ATTACHMENT_FILE');expected=os.environ.get('HILEGA_FACTORY_ATTACHMENT_SHA256')
    if path is None and expected is None and _REFERENCE is None:return None
    from worker_binding import ensure_paused,registration,RegisteredAuthorityWorker
    from market_lab.hilega_execution_port_v1 import adapter as port
    from market_lab.hilega_execution_session_factory_v1 import closed
    try:
        if not _STARTED:ensure_paused(source.s);_STARTED=True
        # A configured pointer cannot cause private descriptor, registration,
        # issuer, context or token reads while the actual order gate is closed.
        try:port.require_live_clearance()
        except port.GateClosed:
            ensure_paused(source.s)
            return dict(closed(),source_at=journal_time(journal),external_attachment_configured=True)
        need(bool(path) and bool(expected),'EXACT_ATTACHMENT_POINTER_PAIR_REQUIRED')
        reference=(str(Path(path)),expected)
        if _REFERENCE is not None:
            need(reference==_REFERENCE,'ATTACHMENT_POINTER_CHANGED_RESTART_REVIEW_REQUIRED')
            need(source is _SOURCE and Path(journal).resolve()==_JOURNAL,'ATTACHMENT_PROCESS_SOURCE_CHANGED')
        value=descriptor(Path(path),expected,source,journal,source.s.now())
        reg=registration(Path(value['registration_file']),value['registration_sha256'])
        need(reg['enabled'] is True,'ATTACHMENT_REQUIRES_EXPLICIT_ENABLED_REGISTRATION')
        bind=reg['expected_binding']
        need(digest(canonical(bind))==value['expected_binding_sha256'],'ATTACHMENT_EXPECTED_BINDING_CHANGED')
        need(bind['release_sha256']==value['release_sha256'] and bind['policy_sha256']==value['policy_sha256']
             and bind['bridge_run_id']==value['bridge_run_id'],'ATTACHMENT_REGISTRATION_RELEASE_POLICY_OR_LEASE_CHANGED')
        if _WORKER is None:
            _WORKER=RegisteredAuthorityWorker(Path(value['registration_file']),value['registration_sha256'],clock=source.s.now)
            _REFERENCE=reference;_SOURCE=source;_JOURNAL=Path(journal).resolve()
        need(_WORKER.path==Path(value['registration_file']) and _WORKER.expected==value['registration_sha256'],'ATTACHMENT_REGISTRATION_POINTER_CHANGED')
        # Existing worker revalidates signed grant, independent pinned issuer,
        # owner/context identity, lease and expiry on every poll.
        result=_WORKER.poll(source,journal)
        return dict(result,source_at=journal_time(journal),external_attachment_configured=True)
    except Exception:
        ensure_paused(source.s)
        raise
