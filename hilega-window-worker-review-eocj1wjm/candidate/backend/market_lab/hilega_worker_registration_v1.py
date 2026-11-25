"""Explicit public registration for CLOSED preparation routing. No execution enrollment."""
import hashlib
import json
from pathlib import Path

MODEL='HILEGA_CLOSED_WORKER_REGISTRATION_V1'
FIELDS={'model','mode','base_release_manifest_sha256','production_execution_enabled','execution_factory_configured'}


def need(ok,reason):
    if not ok:raise ValueError(reason)


class ClosedRegistration:
    def poll(self,bridge,journal):
        from market_lab.hilega_execution_session_factory_v1 import worker_poll
        from worker_binding import default_worker_poll
        return default_worker_poll(bridge,journal)


def load_closed_registration(path,digest):
    p=Path(path);need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in [p,*p.parents]),'REGULAR_PUBLIC_REGISTRATION_REQUIRED')
    raw=p.read_bytes();need(hashlib.sha256(raw).hexdigest()==digest,'APPROVED_REGISTRATION_CHANGED')
    value=json.loads(raw)
    need(type(value) is dict and set(value)==FIELDS and value['model']==MODEL and value['mode']=='CLOSED_PREPARATION_ONLY'
        and value['production_execution_enabled'] is False and value['execution_factory_configured'] is False,'EXACT_CLOSED_REGISTRATION_REQUIRED')
    binding=value['base_release_manifest_sha256']
    need(type(binding) is str and len(binding)==64 and all(c in '0123456789abcdef' for c in binding),'BASE_RELEASE_BINDING_REQUIRED')
    return ClosedRegistration()


def registered_worker_poll(bridge,journal,*,registration=None):
    if registration is None:
        from market_lab.hilega_execution_session_factory_v1 import worker_poll
        return worker_poll(bridge,journal)
    need(type(registration) is ClosedRegistration,'EXACT_CLOSED_REGISTRATION_TYPE_REQUIRED')
    return registration.poll(bridge,journal)
