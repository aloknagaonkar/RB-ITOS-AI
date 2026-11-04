from pathlib import Path
import pytest
from file_transaction import apply_files,restore_files,sha

def entries(tmp_path):
    result=[]
    for i in range(4):
        p=tmp_path/f'file{i}';p.write_bytes(b'old');payload=tmp_path/f'payload{i}';payload.write_bytes(b'new');backup=tmp_path/f'backup{i}';backup.write_bytes(b'old')
        result.append(dict(path=str(p),payload=str(payload),backup=str(backup),old_sha256=sha(b'old'),new_sha256=sha(b'new'),mode=0o600))
    return result
def test_complete_install_and_explicit_source_restore(tmp_path):
    e=entries(tmp_path);apply_files(e);assert all(Path(x['path']).read_bytes()==b'new' for x in e);restore_files(e);assert all(Path(x['path']).read_bytes()==b'old' for x in e)
@pytest.mark.parametrize('stop_at',[0,1,2])
def test_interrupted_chain_restores_all_originals(tmp_path,stop_at):
    e=entries(tmp_path)
    def fail(i):
        if i==stop_at:raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError):apply_files(e,checkpoint=fail)
    restore_files(e);assert all(Path(x['path']).read_bytes()==b'old' for x in e)
def test_external_edit_is_not_overwritten_by_restore(tmp_path):
    e=entries(tmp_path);apply_files(e);Path(e[1]['path']).write_bytes(b'operator-edit')
    with pytest.raises(ValueError,match='EXTERNAL'):restore_files(e)
    assert Path(e[1]['path']).read_bytes()==b'operator-edit'
def test_changed_payload_blocks_before_first_install(tmp_path):
    e=entries(tmp_path);Path(e[3]['payload']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='PAYLOAD'):apply_files(e)
    assert all(Path(x['path']).read_bytes()==b'old' for x in e)
