"""Read-only repo/PID identity and quiescence checks; no process signals or starts."""
import argparse
import json
from pathlib import Path


class ManagedBlocked(ValueError):pass


def _need(value,reason):
    if not value:raise ManagedBlocked(reason)


def role(args):
    if '-m' in args:
        i=args.index('-m')
        if args[i+1:i+2]==['market_lab.runtime'] and len(args)>i+2 and args[i+2] in {'api','worker'}:
            return args[i+2]
    if any(Path(arg).name=='hilega_production_simulator_bridge.py' for arg in args[1:]):
        return 'production-source-worker'
    return None


def processes(root,proc_root=Path('/proc')):
    root=Path(root).resolve();found=[]
    for proc in Path(proc_root).iterdir():
        if not proc.name.isdigit():continue
        try:
            args=[v.decode(errors='replace') for v in (proc/'cmdline').read_bytes().split(b'\0') if v]
            kind=role(args)
            if kind is None:continue
            cwd=(proc/'cwd').resolve(strict=True)
            if cwd!=root:continue
            # stat field 22 (starttime), parsed after final ')' to permit spaces in comm.
            fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
            state=fields[0]
            if state=='Z':continue # An exited zombie cannot access application code/DB.
            found.append(dict(pid=int(proc.name),role=kind,start_ticks=int(fields[19])))
        except FileNotFoundError:
            continue # Process exited during observation.
        except PermissionError:
            raise ManagedBlocked('RELEVANT_PROCESS_IDENTITY_NOT_READABLE') from None
        except (OSError,ValueError,IndexError):
            raise ManagedBlocked('PROCESS_INVENTORY_REQUIRES_REVIEW') from None
    return sorted(found,key=lambda row:(row['role'],row['pid']))


def inspect(root,proc_root=Path('/proc')):
    root=Path(root).resolve();active=processes(root,proc_root);records=[]
    for kind in ('api','worker'):
        path=root/'data/runtime'/f'{kind}.json'
        _need(path.is_file() and not path.is_symlink(),'MANAGED_PID_RECORD_REQUIRED_'+kind.upper())
        data=json.loads(path.read_text())
        _need(data.get('service')==kind and Path(data.get('project_root','')).resolve()==root and
              type(data.get('pid')) is int and data['pid']>0,'MANAGED_PID_RECORD_INVALID_'+kind.upper())
        matches=[r for r in active if r['pid']==data['pid'] and r['role']==kind]
        same_pid=[r for r in active if r['pid']==data['pid']]
        _need(not same_pid or matches,'MANAGED_PID_ROLE_MISMATCH')
        records.append(dict(role=kind,pid=data['pid'],state='MATCHED_RUNNING' if matches else 'NOT_RUNNING_AT_RECORDED_PID'))
    for kind in ('api','worker'):
        _need(sum(r['role']==kind for r in active)<=1,'DUPLICATE_MANAGED_ROLE_REQUIRES_REVIEW')
        live=next((r for r in active if r['role']==kind),None)
        rec=next(r for r in records if r['role']==kind)
        _need(live is None or live['pid']==rec['pid'],'RUNNING_ROLE_NOT_MATCHED_BY_PID_RECORD')
    return dict(status='PID_MANAGED_INVENTORY_VERIFIED',root_matches=True,
                records=records,active_processes=active,quiescent=not active,
                processes_signalled=False,services_started=False,
                scope=['api','worker','production-source-worker'],
                unrelated_observers_and_sandbox_excluded=True)


def require_stopped(root,proc_root=Path('/proc')):
    result=inspect(root,proc_root)
    _need(result['quiescent'],'REPO_API_WORKER_OR_PRODUCTION_SOURCE_STILL_RUNNING')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    try:result=inspect(args.root);print(json.dumps(result));return 0
    except (ManagedBlocked,OSError,ValueError):
        import sys
        exc=sys.exc_info()[1]
        reason=str(exc) if isinstance(exc,ManagedBlocked) else 'MANAGED_INVENTORY_UNAVAILABLE'
        print(json.dumps(dict(status='BLOCKED',reason=reason,processes_signalled=False)));return 2


if __name__=='__main__':raise SystemExit(main())
