"""Explicit pending-window registry recovery; disposable adapter only."""
import argparse,json,subprocess,sys
from pathlib import Path
from window import need,save

def registry_windows(registry):
    registry=Path(registry).absolute();need(registry.is_file() and not any(x.is_symlink() for x in [registry,*registry.parents]),'REGULAR_REGISTRY_REQUIRED')
    data=json.loads(registry.read_text());need(data.get('model')=='HILEGA_DISPOSABLE_RECOVERY_REGISTRY_V1','DISPOSABLE_REGISTRY_REQUIRED')
    base=registry.parent.resolve();out=[]
    for name in data['windows']:
        path=Path(name);need(not path.is_absolute() and '..' not in path.parts and bool(path.parts),'REGISTRY_WINDOW_ESCAPE')
        workspace=base/path
        need(workspace.is_dir() and not any(x.is_symlink() for x in [workspace,*workspace.parents]),'REGULAR_REGISTERED_WINDOW_REQUIRED')
        need(workspace.resolve().is_relative_to(base),'REGISTRY_WINDOW_ESCAPE')
        marker=workspace/'DISPOSABLE-WINDOW.json';need(marker.is_file() and not marker.is_symlink(),'DISPOSABLE_MARKER_REQUIRED')
        need(json.loads(marker.read_text())==dict(model='HILEGA_DISPOSABLE_WINDOW_V1',workspace=str(workspace.resolve())),'DISPOSABLE_MARKER_CHANGED')
        state=workspace/'WINDOW.json';need(state.is_file() and not state.is_symlink(),'REGULAR_PENDING_STATE_REQUIRED')
        out.append((workspace,state,json.loads(state.read_text())))
    return out

def recover_all(registry,pause):
    recovered=[]
    for workspace,path,state in registry_windows(registry):
        need(state.get('phase') in {'CLOSED','DEADLINE_PERSISTED','ARM_REQUESTED'},'UNKNOWN_WINDOW_PHASE')
        if state['phase']=='CLOSED':continue
        pause(workspace)
        save(path,dict(state,phase='CLOSED',closed_by='PENDING_REGISTRY_RECOVERY'))
        recovered.append(workspace.name)
    return recovered

def assert_admission(registry):
    need(all(state.get('phase')=='CLOSED' for _,_,state in registry_windows(registry)),'PENDING_WINDOW_BLOCKS_ADMISSION')

def main():
    p=argparse.ArgumentParser();p.add_argument('--registry',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);a=p.parse_args()
    def pause(workspace):
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('managed_guard.py')),'--bundle',str(a.bundle),'--workspace',str(workspace),'--recover'],capture_output=True,text=True,timeout=15)
        (workspace/'REGISTRY-RECOVERY.log').write_text(result.stdout+result.stderr)
        need(result.returncode==0,'REGISTERED_WINDOW_PAUSE_FAILED')
    recovered=recover_all(a.registry,pause);assert_admission(a.registry)
    save(a.registry.parent/'ADMISSION-READY.json',dict(status='DISPOSABLE_RECOVERY_COMPLETE',recovered_windows=recovered,production_execution_enabled=False));return 0
if __name__=='__main__':raise SystemExit(main())
