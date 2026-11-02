"""Exact worker staging, concrete probe plan and disposable registration rollback."""
import hashlib
import json
from pathlib import Path


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def transform(text):
    changes=[('from market_lab.hilega_execution_session_factory_v1 import worker_poll',
        'from market_lab.hilega_worker_registration_v1 import registered_worker_poll,load_closed_registration'),
        ('    a=p.parse_args()',"    p.add_argument('--closed-registration',type=Path)\n    p.add_argument('--closed-registration-sha256')\n    a=p.parse_args()"),
        ('        try:\n            while True:',"        try:\n            registration=None\n            if a.closed_registration is not None or a.closed_registration_sha256 is not None:\n                if not preparation_only or a.closed_registration is None or a.closed_registration_sha256 is None:\n                    raise Blocked('EXACT_CLOSED_REGISTRATION_ARGUMENTS_REQUIRED')\n                registration=load_closed_registration(a.closed_registration,a.closed_registration_sha256)\n            while True:"),
        ('result=worker_poll(bridge,a.source)','result=registered_worker_poll(bridge,a.source,registration=registration)')]
    for before,after in changes:
        need(text.count(before)==1,'EXACT_WORKER_REGISTRATION_ANCHOR_REQUIRED');text=text.replace(before,after,1)
    compile(text,'registered-worker.py','exec');return text


def probe_command(plan):
    unit=plan['probe_unit'];need(unit.startswith('hilega-closed-registration-probe-') and unit.endswith('.service')
        and all(c.isalnum() or c in '-.' for c in unit),'ISOLATED_PROBE_UNIT_REQUIRED')
    return ['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot',
        '--property=NoNewPrivileges=yes','--property=RestrictAddressFamilies=AF_UNIX','--property=RuntimeMaxSec=20',
        '--working-directory='+plan['release_folder'],plan['python'],'-B',plan['probe_script'],
        '--registration',plan['registration'],'--sha256',plan['registration_sha256']]


def worker_rollback(review,old,new):
    root=review/'worker-rollback-rehearsal';root.mkdir();p=root/'worker.py';backup=root/'worker.py.backup'
    p.write_bytes(old);backup.write_bytes(old);p.write_bytes(new);need(p.read_bytes()==new,'STAGED_WORKER_APPLY_FAILED')
    p.write_bytes(backup.read_bytes());need(p.read_bytes()==old,'STAGED_WORKER_ROLLBACK_FAILED')
    return dict(status='DISPOSABLE_REGISTERED_WORKER_ROLLBACK_PASS',previous_sha256=sha(old),candidate_sha256=sha(new),
        installed_worker_restored=False,live_database_restored=False)
