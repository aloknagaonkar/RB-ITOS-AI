import os
import pytest
from transaction import atomic, replace_all, restore_all, sha


@pytest.fixture
def setup_files(tmp_path):
    payload, backup = tmp_path/'payload', tmp_path/'backup'
    payload.mkdir(); backup.mkdir()
    entries = []
    for i in range(2):
        target = tmp_path/('target'+str(i))
        old, new = ('old'+str(i)).encode(), ('new'+str(i)).encode()
        atomic(target, old, 0o640)
        atomic(payload/str(i), new, 0o600)
        atomic(backup/str(i), old, 0o600)
        entries.append(dict(destination=str(target), payload=str(i), old_sha256=sha(old), new_sha256=sha(new), mode=0o400, old_mode=0o640))
    return entries, payload, backup


def test_install_and_restore_exact_bytes_and_modes(setup_files):
    entries, payload, backup = setup_files
    replace_all(entries, payload, backup)
    for e in entries:
        assert sha(open(e['destination'], 'rb').read()) == e['new_sha256']
        assert os.stat(e['destination']).st_mode & 0o777 == 0o400
    restore_all(entries, backup)
    for e in entries:
        assert sha(open(e['destination'], 'rb').read()) == e['old_sha256']
        assert os.stat(e['destination']).st_mode & 0o777 == 0o640


@pytest.mark.parametrize('stop_after', [0, 1])
def test_interrupted_replacement_restores_mixed_state(setup_files, stop_after):
    entries, payload, backup = setup_files
    def fail(index):
        if index == stop_after:
            raise RuntimeError('simulated interruption')
    with pytest.raises(RuntimeError):
        replace_all(entries, payload, backup, checkpoint=fail)
    restore_all(entries, backup)
    assert all(sha(open(e['destination'], 'rb').read()) == e['old_sha256'] for e in entries)


@pytest.mark.parametrize('which', ['target', 'payload', 'backup'])
def test_changed_input_blocks_before_replacement(setup_files, which):
    entries, payload, backup = setup_files
    from pathlib import Path
    p = dict(target=Path(entries[1]['destination']), payload=payload/'1', backup=backup/'1')[which]
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):
        replace_all(entries, payload, backup)
    assert sha(Path(entries[0]['destination']).read_bytes()) == entries[0]['old_sha256']


def test_external_edit_blocks_entire_rollback(setup_files):
    from pathlib import Path
    entries, payload, backup = setup_files
    replace_all(entries, payload, backup)
    p = Path(entries[1]['destination']); p.chmod(0o600); p.write_bytes(b'external')
    with pytest.raises(ValueError, match='EXTERNAL_CHANGE'):
        restore_all(entries, backup)
    assert sha(Path(entries[0]['destination']).read_bytes()) == entries[0]['new_sha256']


def test_symlink_target_rejected(setup_files):
    from pathlib import Path
    entries, payload, backup = setup_files
    p = Path(entries[0]['destination']); p.unlink(); p.symlink_to(backup/'0')
    with pytest.raises(ValueError, match='REGULAR_ABSOLUTE'):
        replace_all(entries, payload, backup)
