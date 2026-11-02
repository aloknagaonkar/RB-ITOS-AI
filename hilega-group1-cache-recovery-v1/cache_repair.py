"""Quarantine generated caches and protect manifest-bound bundle bytes from writes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def inventory(root,manifest):
    root=Path(root);need(root.is_dir() and not any(p.is_symlink() for p in [root,*root.absolute().parents]),'REGULAR_BUNDLE_ROOT_REQUIRED')
    for p in root.rglob('*'):need(not p.is_symlink(),'SYMLINK_IN_BUNDLE_FORBIDDEN')
    for name,digest in manifest['files'].items():
        rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'RELATIVE_MANIFEST_PATH_REQUIRED')
        p=root/rel;need(p.is_file() and sha(p.read_bytes())==digest,'APPROVED_BUNDLE_FILE_CHANGED')
    expected=set(manifest['files'])|{'RELEASE-MANIFEST.json'}
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    extras=[]
    for name in sorted(actual-expected):
        p=root/name
        need(p.parent.name=='__pycache__' and p.suffix=='.pyc','NONCACHE_UNMANIFESTED_FILE_REQUIRES_REVIEW')
        source=Path(importlib.util.source_from_cache(str(p)))
        rel=source.relative_to(root).as_posix()
        need(rel in manifest['files'] and rel.endswith('.py'),'CACHE_SOURCE_NOT_IN_APPROVED_MANIFEST')
        need(p.stat().st_nlink==1,'CACHE_HARDLINK_REQUIRES_REVIEW')
        extras.append(dict(path=name,source=rel,sha256=sha(p.read_bytes())))
    return extras


def protect(root,manifest,quarantine):
    extras=inventory(root,manifest);quarantine.mkdir(mode=0o700)
    modes={p.relative_to(root).as_posix() if p!=root else '.':stat.S_IMODE(p.stat().st_mode)
        for p in [root,*root.rglob('*')]}
    for row in extras:
        p=root/row['path'];target=quarantine/row['path'];target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        need(sha(p.read_bytes())==row['sha256'],'CACHE_CHANGED_BEFORE_QUARANTINE')
        shutil.copyfile(p,target)
        with target.open('rb+') as f:os.fsync(f.fileno())
        need(sha(target.read_bytes())==row['sha256'],'QUARANTINE_COPY_CHANGED');target.chmod(0o600);p.unlink()
    # No manifest file is deleted or modified. Empty cache directories are retained read-only.
    for p in root.rglob('*'):
        p.chmod(0o500 if p.is_dir() else 0o400)
    root.chmod(0o500)
    need(not inventory(root,manifest),'CACHE_FILES_REMAIN_AFTER_REPAIR')
    need(not any(os.access(p,os.W_OK) for p in [root,*root.rglob('*')]),'IMMUTABLE_BUNDLE_STILL_WRITABLE')
    return dict(quarantined=extras,original_modes=modes,approved_file_bytes_changed=False,installed_bundle_read_only=True)
