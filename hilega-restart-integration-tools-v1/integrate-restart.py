"""Back up and integrate existing shell entry points; never signal processes."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

ANCHORS={
 'start.sh':('start_service "api"\nstart_service "worker"','start'),
 'stop.sh':('stop_service "worker"\nstop_service "api"','stop'),
 'status.sh':('service_status "api"\nservice_status "worker"','status'),
}

def patch_shell(name,text):
    if 'hilega_supervised_control.py' in text:
        raise ValueError('ALREADY_INTEGRATED')
    if name=='restart.sh':
        anchor='"$ROOT/scripts/stop.sh"'
        if text.count(anchor)!=1: raise ValueError('RESTART_ANCHOR_CHANGED')
        return text.replace(anchor,'cd "$ROOT"\n\n'+anchor,1)
    anchor,action=ANCHORS[name]
    if text.count(anchor)!=1: raise ValueError('SHELL_ANCHOR_CHANGED_'+name)
    block='''if "$PYTHON" "$ROOT/scripts/hilega_supervised_control.py" mode; then
    "$PYTHON" "$ROOT/scripts/hilega_supervised_control.py" ACTION
else
    supervision_rc=$?
    if [[ "$supervision_rc" -ne 10 ]]; then
        echo "ERROR: supervision requires review; legacy launch/stop blocked."
        exit "$supervision_rc"
    fi
LEGACY
fi'''.replace('ACTION',action).replace('LEGACY',anchor)
    return text.replace(anchor,block,1)

def main(apply=False):
    root=Path.home()/'RB-ITOS-AI'
    helper_source=Path(__file__).resolve().parent/'hilega_supervised_control.py'
    helper_target=root/'scripts/hilega_supervised_control.py'
    if helper_target.exists() or helper_target.is_symlink():
        raise ValueError('HELPER_ALREADY_EXISTS')
    code=helper_source.read_text();compile(code,str(helper_target),'exec')
    originals={};updated={}
    for name in (*ANCHORS,'restart.sh'):
        p=root/'scripts'/name
        if not p.is_file() or p.is_symlink(): raise ValueError('REGULAR_SCRIPT_REQUIRED')
        originals[p]=p.read_bytes()
        updated[p]=patch_shell(name,originals[p].decode())
    with tempfile.TemporaryDirectory() as d:
        for p,text in updated.items():
            candidate=Path(d)/p.name;candidate.write_text(text)
            subprocess.run(['bash','-n',str(candidate)],check=True)
    if not apply:
        print('RESTART_INTEGRATION_CHECKS_PASS; no files or processes changed')
        return
    backup=Path(tempfile.mkdtemp(prefix='hilega-restart-integration-',dir=root/'backups'))
    os.chmod(backup,0o700)
    for p,raw in originals.items(): (backup/p.name).write_bytes(raw)
    for p,raw in originals.items():
        if p.read_bytes()!=raw: raise ValueError('SCRIPT_CHANGED_DURING_INTEGRATION')
    def write(p,text,mode):
        fd,name=tempfile.mkstemp(dir=p.parent)
        try:
            os.fchmod(fd,mode)
            with os.fdopen(fd,'w') as s:s.write(text);s.flush();os.fsync(s.fileno())
            os.replace(name,p)
        finally:
            if os.path.exists(name):os.unlink(name)
    # Install helper first so interrupted edits cannot invoke a missing file.
    write(helper_target,code,0o600)
    for p,text in updated.items():write(p,text,p.stat().st_mode & 0o777)
    print('RESTART_ENTRYPOINTS_INTEGRATED; no processes signalled or services started')
    print('Backup:',backup)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('check','apply'))
    try:main(p.parse_args().action=='apply')
    except Exception as exc:
        print('STOP:',str(exc) if type(exc) is ValueError else type(exc).__name__)
        raise SystemExit(1)
