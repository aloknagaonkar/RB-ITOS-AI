"""Exact file-only transaction; database restoration is deliberately excluded."""
import hashlib,os,stat,tempfile
from pathlib import Path

def need(ok,code):
    if not ok:raise ValueError(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def atomic(p,data,mode=0o600):
    need(not any(q.is_symlink() for q in (p,*p.parents)),'SYMLINK_OUTPUT_REJECTED')
    fd,name=tempfile.mkstemp(prefix=p.name+'.warmup-',dir=p.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,p);d=os.open(p.parent,os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.exists(name):os.unlink(name)
def apply_files(entries,*,checkpoint=lambda index:None):
    for e in entries:
        need(sha(regular(Path(e['path'])))==e['old_sha256'],'SOURCE_CHANGED_BEFORE_INSTALL')
        need(sha(regular(Path(e['payload'])))==e['new_sha256'],'PAYLOAD_CHANGED')
        need(sha(regular(Path(e['backup'])))==e['old_sha256'],'BACKUP_CHANGED')
    for i,e in enumerate(entries):
        need(sha(regular(Path(e['path'])))==e['old_sha256'],'SOURCE_CHANGED_DURING_INSTALL')
        atomic(Path(e['path']),regular(Path(e['payload'])),e['mode']);checkpoint(i)
    for e in entries:need(sha(regular(Path(e['path'])))==e['new_sha256'],'INSTALL_VERIFICATION_FAILED')
def restore_files(entries):
    for e in entries:
        need(sha(regular(Path(e['path']))) in {e['old_sha256'],e['new_sha256']},'EXTERNAL_SOURCE_EDIT_BLOCKS_RESTORE')
        need(sha(regular(Path(e['backup'])))==e['old_sha256'],'BACKUP_CHANGED')
    for e in reversed(entries):atomic(Path(e['path']),regular(Path(e['backup'])),e['mode'])
