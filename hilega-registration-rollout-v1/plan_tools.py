"""Exact file plans for closed pause recovery; no service actions."""
import hashlib,json
from pathlib import Path

def sha(raw):return hashlib.sha256(raw).hexdigest()
def need(ok,reason):
    if not ok:raise ValueError(reason)
def quote(value):
    need(all(x not in value for x in ('\n','\r','%','$')),'UNSUPPORTED_SYSTEMD_PATH')
    return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
def unit(python,script,config,digest):
    command=' '.join(quote(str(x)) for x in (python,'-I','-B',script,'--config',config,'--sha256',digest))
    return ('[Unit]\nDescription=Hilega closed controller pause recovery\n\n[Service]\nType=oneshot\nRemainAfterExit=yes\nUMask=0077\nTimeoutStartSec=90\nExecStart='+command+'\n').encode()
def dropin():return b'[Unit]\nRequires=hilega-closed-pause-recovery.service\nAfter=hilega-closed-pause-recovery.service\n'
def exact_files(entries):
    need(len({e['destination'] for e in entries})==len(entries),'DUPLICATE_INSTALL_DESTINATION')
    for e in entries:
        p=Path(e['destination']);need(p.is_absolute() and '..' not in p.parts,'ABSOLUTE_INSTALL_DESTINATION_REQUIRED')
        need(e['old_sha256'] is None,'EXISTING_RECOVERY_INSTALL_REQUIRES_SEPARATE_UPGRADE_PLAN')
    return entries
