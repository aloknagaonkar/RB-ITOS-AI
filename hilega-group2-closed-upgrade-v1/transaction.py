"""Compare-and-swap file replacement with verified backups and explicit rollback."""
import hashlib
import os
from pathlib import Path


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def regular(path):
    p = Path(path)
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p, *p.parents)), 'REGULAR_ABSOLUTE_FILE_REQUIRED')
    return p.read_bytes()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw, mode):
    p = Path(path)
    need(not any(q.is_symlink() for q in (p, *p.parents)), 'SYMLINK_WRITE_FORBIDDEN')
    tmp = p.with_name(p.name+'.upgrade-new')
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, p)
        fd = os.open(p.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def replace_all(entries, payload, backups, *, checkpoint=lambda index: None):
    # Validate the whole set before the first replacement.
    for index, entry in enumerate(entries):
        need(sha(regular(Path(entry['destination']))) == entry['old_sha256'], 'OLD_FILE_CHANGED')
        need(sha(regular(payload/entry['payload'])) == entry['new_sha256'], 'PAYLOAD_CHANGED')
        need(sha(regular(backups/str(index))) == entry['old_sha256'], 'BACKUP_CHANGED')
    for index, entry in enumerate(entries):
        target = Path(entry['destination'])
        need(sha(regular(target)) == entry['old_sha256'], 'TARGET_CHANGED_DURING_REPLACE')
        atomic(target, regular(payload/entry['payload']), entry['mode'])
        checkpoint(index)


def restore_all(entries, backups):
    # External edits stop rollback before any overwrite. Old/new mixtures are
    # legitimate after a crash between independent atomic replacements.
    for index, entry in enumerate(entries):
        need(sha(regular(Path(entry['destination']))) in {entry['old_sha256'], entry['new_sha256']}, 'EXTERNAL_CHANGE_BLOCKS_ROLLBACK')
        need(sha(regular(backups/str(index))) == entry['old_sha256'], 'BACKUP_CHANGED')
    for index, entry in reversed(list(enumerate(entries))):
        atomic(Path(entry['destination']), regular(backups/str(index)), entry['old_mode'])
