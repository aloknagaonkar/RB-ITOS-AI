"""Deploy the VM-validated closed exit-recording patch while preserving closed execution."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

PIN="833990b9eabc3f57d8a382638ba134d824937d9109499582f4dd6291689ec72d"
INVENTORY_BLOB="1504472bd17c5d062321e138627d1dc6dce0f355"
UNITS={"worker":"hilega-worker.service","api":"hilega-api.service",
       "production-source-worker":"hilega-production-source-worker.service"}
IDENTITIES="backups/hilega-preparation-activation-cvtlkibq/maintenance.json"
TARGETS={
 "backend/market_lab/hilega_preparation_runtime_v1/source.py":
 "runtime/market_lab/hilega_preparation_runtime_v1/source.py",
 "backend/market_lab/hilega_preparation_runtime_v1/exit_dispatch.py":
 "runtime/market_lab/hilega_preparation_runtime_v1/exit_dispatch.py"}


def need(ok,reason):
    if not ok:raise ValueError(reason)


def regular(path):
    path=Path(path).absolute()
    need(path.is_file() and not path.is_symlink(),"REGULAR_FILE_REQUIRED")
    for parent in path.parents:need(not parent.is_symlink(),"SYMLINK_PARENT_FORBIDDEN")
    return path


def sha(path):return hashlib.sha256(regular(path).read_bytes()).hexdigest()


def atomic_write(path,raw,mode=0o600):
    fd,name=tempfile.mkstemp(prefix=".reservation-maintenance-",dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,"wb") as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def write_json(path,value):
    atomic_write(path,json.dumps(value,indent=2).encode())


def call(args,*,cwd=None,env=None):
    result=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=45)
    need(result.returncode==0,"SERVICE_OR_CHECK_COMMAND_FAILED")
    return result.stdout.strip()


def unit_states():
    result={}
    for role,unit in UNITS.items():
        raw=call(["systemctl","--user","show",unit,
            "-p","LoadState","-p","ActiveState","-p","SubState","-p","MainPID"])
        row=dict(line.split("=",1) for line in raw.splitlines() if "=" in line)
        need(row.get("LoadState")=="loaded","SERVICE_NOT_LOADED")
        result[role]=row
    return result


def validate_running(states,rows):
    need(len(rows)==3 and {r["role"] for r in rows}==set(UNITS),
         "EXACTLY_THREE_MANAGED_PROCESSES_REQUIRED")
    for role,row in states.items():
        need(row.get("ActiveState")=="active" and row.get("SubState")=="running"
             and int(row.get("MainPID","0"))>0,"SERVICE_NOT_RUNNING")
        matches=[p for p in rows if p["role"]==role]
        need(len(matches)==1 and matches[0]["pid"]==int(row["MainPID"]),
             "SERVICE_INVENTORY_PID_MISMATCH")


def validate_stopped(states,rows):
    need(not rows,"DETACHED_OR_MANAGED_APPLICATION_STILL_RUNNING")
    need(all(s.get("ActiveState")=="inactive" and s.get("SubState")=="dead"
         and s.get("MainPID")=="0" for s in states.values()),"SERVICES_NOT_STOPPED")


def check_result(value):
    need(value.get("status") in {"PAUSED_SAFE_SOURCE_FRESH",
         "PAUSED_SAFE_WAITING_FOR_FRESH_SOURCE"},"PAUSED_SAFETY_REQUIRED")
    need(value.get("process_identities_match") is True
         and value.get("controller_mode")=="PAUSED"
         and value.get("execution_route")=="PREPARATION_ONLY"
         and value.get("journal_prefix_matches") is True
         and type(value.get("journal_tail_remaining_records")) is int
         and value["journal_tail_remaining_records"]==0
         and value.get("production_ready") is False,"PAUSED_STATE_OR_JOURNAL_INVALID")
    counts=value.get("activity_counts")
    need(isinstance(counts,dict) and len(counts)==7
         and all(type(v) is int and v==0 for v in counts.values()),
         "APPLICATION_ACTIVITY_REQUIRES_REVIEW")
    need(type(value.get("local_cash_reservation_count")) is int
         and value["local_cash_reservation_count"]==0,
         "LOCAL_RESERVATION_REQUIRES_REVIEW")


def release(root,*,installed=False,allow_mixed=False):
    package=regular(root/"hilega-exit-dispatch-closed-tools-v1/manifest.json").parent
    need(sha(package/"manifest.json")==PIN,"INTEGRATION_MANIFEST_CHANGED")
    manifest=json.loads((package/"manifest.json").read_text())
    manifest["runtime_targets"]=dict(TARGETS)
    for name,expected in manifest["package_sha256"].items():
        need(sha(package/name)==expected,"STAGED_PACKAGE_CHANGED")
    for name,expected in manifest["baseline_sha256"].items():
        path=root/name
        if allow_mixed and name in TARGETS:
            new=manifest["package_sha256"][TARGETS[name]]
            if path.exists() and sha(path)==new:
                continue
        if installed and name in TARGETS:
            expected=manifest["package_sha256"][TARGETS[name]]
        if expected is None:
            need(not path.exists() and not path.is_symlink(),"NEW_TARGET_ALREADY_EXISTS")
        else:need(sha(path)==expected,"INSTALLED_SOURCE_CHANGED")
    reports=sorted(package.glob("CLOSED_EXIT_DISPATCH_REGRESSION-*.json"))
    need(bool(reports),"VM_REGRESSION_REPORT_REQUIRED")
    proof=json.loads(regular(reports[-1]).read_text())
    need(proof.get("status")=="PASS" and proof.get("pytest_exit_code")==0
         and proof.get("local_unit_tests_passed")==10
         and proof.get("package_manifest_sha256")==PIN
         and proof.get("baseline_sha256")==manifest["baseline_sha256"]
         and all(proof.get(k) is False for k in (
             "applied","services_restarted","database_migration_performed",
             "production_execution_enabled"))
         and proof.get("exit_dispatch_scope")=="DURABLE_REFUSED_NON_EXECUTABLE_ONLY"
         and proof.get("live_exit_submission_integrated") is False
         and proof.get("reservation_release_permission") is False,
         "VM_REGRESSION_PROOF_INVALID")
    return package,manifest


def inventory_module(root):
    path=regular(root/"hilega-production-application-deployment/managed_processes.py")
    raw=path.read_bytes()
    need(hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==INVENTORY_BLOB,
         "MANAGED_INVENTORY_SOURCE_CHANGED")
    spec=importlib.util.spec_from_file_location("reservation_deployment_inventory",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def activity(root):
    app=root/"data/research/hilega-production-workspace/sim.sqlite"
    broker=root/"data/research/hilega-broker-adapter-closed/adapter.sqlite"
    for path in (app,broker):
        regular(path)
        with path.open("rb") as stream:header=stream.read(20)
        need(header[:16]==b"SQLite format 3\x00" and header[18:20]==b"\x01\x01",
             "ROLLBACK_JOURNAL_DATABASE_REQUIRED")
    with closing(sqlite3.connect(app.as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("ATTACH DATABASE ? AS broker",(broker.as_uri()+"?mode=ro",))
        db.execute("BEGIN")
        control=json.loads(db.execute("SELECT data FROM control WHERE id=1").fetchone()[0])
        route=json.loads(db.execute("SELECT data FROM preparation_route WHERE id=1").fetchone()[0])
        need(control.get("mode")=="PAUSED"
             and control.get("production_execution_enabled") is False,
             "PAUSED_CLOSED_CONTROL_REQUIRED")
        need(route==dict(route="PREPARATION_ONLY",model="APPLICATION_PREPARATION_ROUTE_V1"),
             "PREPARATION_ROUTE_REQUIRED")
        stop=db.execute("SELECT generation,handled FROM sim_stop_state WHERE id=1").fetchone()
        need(stop is not None and stop[0]==stop[1],"UNHANDLED_STOP_REQUIRES_REVIEW")
        meta=json.loads(db.execute("SELECT data FROM broker.meta WHERE id=1").fetchone()[0])
        need(meta.get("mode")=="LIVE_CLOSED","CLOSED_ADAPTER_REQUIRED")
        for table in ("intents","sim_orders","sim_fills","sim_allocation_reservations",
                      "preparation_plans","preparation_shadow_holds","preparation_outbox"):
            need(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]==0,
                 "APPLICATION_ACTIVITY_REQUIRES_REVIEW")
        for table in ("requests","attempts","receipts"):
            need(db.execute("SELECT COUNT(*) FROM broker."+table).fetchone()[0]==0,
                 "ADAPTER_ACTIVITY_REQUIRES_REVIEW")
        for table in ("preparation_cash_reservations","preparation_request_bindings"):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                need(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]==0,
                     "LOCAL_RESERVATION_OR_BINDING_REQUIRES_REVIEW")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='preparation_exit_dispatch'").fetchone():
            for raw, in db.execute("SELECT data FROM preparation_exit_dispatch"):
                row=json.loads(raw)
                need(row.get("model")=="HILEGA_APPLICATION_CLOSED_EXIT_DISPATCH_V1"
                     and row.get("dispatch_status")=="REFUSED_CLOSED"
                     and row.get("exit_quantity") is None
                     and row.get("parent_request_id") is None
                     and all(row.get(k) is False for k in (
                         "orders_sent","production_execution_enabled","entry_permission",
                         "executable_request_created","automatic_execution_eligible",
                         "reservation_release_permission")),
                     "EXIT_DISPATCH_ACTIVITY_REQUIRES_REVIEW")
        db.rollback()


def paused_check(root):
    env=dict(os.environ);env["PYTHONPATH"]=str(root/"backend")+os.pathsep+str(root)
    value=json.loads(call([str(root/".venv/bin/python"),
        str(root/"check-preparation-paused.py")],cwd=root,env=env))
    check_result(value)
    return value


def api_health():
    with urlopen("http://127.0.0.1:8123/api/health",timeout=3) as response:
        raw=response.read(16385)
    need(len(raw)<=16384,"API_HEALTH_RESPONSE_TOO_LARGE")
    value=json.loads(raw)
    need(value.get("status")=="ok" and value.get("execution")=="not_enabled",
         "API_EXECUTION_NOT_DISABLED")
    return value


def check(root):
    release(root)
    module=inventory_module(root)
    rows=module.inspect(root)["active_processes"]
    validate_running(unit_states(),rows)
    paused_check(root);activity(root);api_health()
    regular(root/IDENTITIES)
    return rows


def patch_files(root,package,manifest,backup):
    targets=manifest["runtime_targets"]
    originals={}
    for name in targets:
        path=root/name
        if path.exists():
            regular(path)
            originals[name]=(path.read_bytes(),path.stat().st_mode&0o777)
            saved=backup/"files"/name;saved.parent.mkdir(parents=True,exist_ok=True)
            atomic_write(saved,originals[name][0],originals[name][1])
        else:originals[name]=None
    write_json(backup/"originals.json",{
        name:None if value is None else dict(
            sha256=hashlib.sha256(value[0]).hexdigest(),mode=value[1])
        for name,value in originals.items()})
    changed=[]
    try:
        for name,relative in targets.items():
            raw=regular(package/relative).read_bytes()
            compile(raw,name,"exec")
            mode=originals[name][1] if originals[name] else 0o644
            atomic_write(root/name,raw,mode);changed.append(name)
    except BaseException:
        for name in reversed(changed):
            old=originals[name]
            if old is None:(root/name).unlink()
            else:atomic_write(root/name,old[0],old[1])
        raise


def refresh_identities(root,rows,backup):
    path=regular(root/IDENTITIES)
    before=path.read_bytes()
    saved=backup/"maintenance-identities-before.json"
    if not saved.exists():atomic_write(saved,before)
    value=json.loads(before)
    need(isinstance(value.get("children"),dict),"MAINTENANCE_CHILD_IDENTITIES_REQUIRED")
    pids={row["role"]:row["pid"] for row in rows}
    value["children"].update(api=pids["api"],worker=pids["worker"],
        source=pids["production-source-worker"])
    atomic_write(path,json.dumps(value,indent=2).encode(),path.stat().st_mode&0o777)


def verify(root,*,installed=True):
    release(root,installed=installed)
    module=inventory_module(root);rows=module.inspect(root)["active_processes"]
    validate_running(unit_states(),rows)
    paused_check(root);activity(root);api_health()
    return rows


def apply(root):
    os.umask(0o077)
    rows=check(root)
    package,manifest=release(root)
    backups=root/"backups"
    need(backups.is_dir() and not backups.is_symlink(),"BACKUP_DIRECTORY_REQUIRED")
    backup=Path(tempfile.mkdtemp(prefix="hilega-exit-dispatch-maintenance-",dir=backups))
    record=backup/"transaction.json"
    state=dict(phase="PREPARED",previous_processes=rows,backup=str(backup),
        package_manifest_sha256=PIN,
        production_execution_enabled=False,database_migration_performed=False)
    write_json(record,state)
    try:
        # Scope is exactly the three previously validated user units.
        state["phase"]="STOPPING";write_json(record,state)
        call(["systemctl","--user","stop",*UNITS.values()])
        module=inventory_module(root)
        validate_stopped(unit_states(),module.processes(root))
        activity(root);release(root)
        state["phase"]="APPLYING_CODE";write_json(record,state)
        patch_files(root,package,manifest,backup)
        state["phase"]="CODE_APPLIED_SERVICES_STOPPED";write_json(record,state)
        print(json.dumps(dict(status=state["phase"],backup=str(backup))),flush=True)
        release(root,installed=True)
        state["phase"]="STARTING";write_json(record,state)
        for unit in UNITS.values():
            state["starting_unit"]=unit;write_json(record,state)
            call(["systemctl","--user","start",unit])
        deadline=time.monotonic()+30
        last="STARTUP_VERIFICATION_PENDING"
        while time.monotonic()<deadline:
            try:
                module=inventory_module(root)
                rows=module.inspect(root)["active_processes"]
                validate_running(unit_states(),rows)
                refresh_identities(root,rows,backup)
                verified=verify(root)
                break
            except Exception as exc:
                last=str(exc) if re.fullmatch("[A-Z][A-Z0-9_]{0,179}",str(exc)) else type(exc).__name__
                time.sleep(1)
        else:raise ValueError(last)
        state.update(phase="DEPLOYED_PAUSED_VERIFIED",processes=verified,
            configuration_changed=False,execution_route="PREPARATION_ONLY",
            controller_mode="PAUSED",daily_loss_limit_required=False,
            entry_allocation_fraction="0.50",live_exit_submission_integrated=False,
            reservation_release_permission=False)
        state.pop("starting_unit",None)
        write_json(record,state)
        print(json.dumps(dict(state,status="CLOSED_EXIT_DISPATCH_DEPLOYED_PAUSED_VERIFIED"),indent=2))
    except BaseException:
        state["failure_after_phase"]=state["phase"]
        state["phase"]="STOPPED_FOR_REVIEW_NO_AUTOMATIC_RETRY"
        # A startup failure may leave some units running. Request one stop of
        # the same three units, without restarting or restoring code implicitly.
        if state["failure_after_phase"]=="STARTING":
            try:
                call(["systemctl","--user","stop",*UNITS.values()])
                validate_stopped(unit_states(),inventory_module(root).processes(root))
                state["failure_cleanup_services_stopped"]=True
            except Exception:
                state["failure_cleanup_services_stopped"]=False
        write_json(record,state)
        print(json.dumps(dict(status=state["phase"],backup=str(backup),
            failure_after_phase=state["failure_after_phase"],
            starting_unit=state.get("starting_unit"),
            automatic_retry=False,production_execution_enabled=False)),flush=True)
        raise



def restore_files(root,backup,manifest):
    saved=json.loads(regular(backup/"originals.json").read_text())
    need(set(saved)==set(TARGETS),"EXACT_ROLLBACK_TARGETS_REQUIRED")
    # Verify every backup before the first write. Never overwrite drift.
    for name,entry in saved.items():
        expected=manifest["baseline_sha256"][name]
        if expected is None:
            need(entry is None,"ROLLBACK_ORIGINAL_STATE_MISMATCH")
        else:
            need(isinstance(entry,dict) and entry.get("sha256")==expected
                 and type(entry.get("mode")) is int
                 and 0<=entry["mode"]<=0o777,
                 "ROLLBACK_ORIGINAL_STATE_MISMATCH")
            need(sha(backup/"files"/name)==expected,"ROLLBACK_BACKUP_CHANGED")
    for name,entry in saved.items():
        target=root/name
        if entry is None:
            if target.exists():
                regular(target);target.unlink()
                fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(fd)
                finally:os.close(fd)
        else:
            atomic_write(target,regular(backup/"files"/name).read_bytes(),entry["mode"])


def rollback(root,backup):
    backup=Path(backup).absolute()
    regular(backup/"transaction.json")
    need(backup.parent==root/"backups"
         and backup.name.startswith("hilega-exit-dispatch-maintenance-"),
         "SCOPED_MAINTENANCE_BACKUP_REQUIRED")
    state=json.loads((backup/"transaction.json").read_text())
    need(state.get("package_manifest_sha256")==PIN
         and state.get("backup")==str(backup),"ROLLBACK_TRANSACTION_MISMATCH")
    need(state.get("phase") not in {"ROLLED_BACK_PAUSED_VERIFIED","ROLLING_BACK"},
         "ROLLBACK_ALREADY_COMPLETED_OR_INTERRUPTED")
    package,manifest=release(root,allow_mixed=True)
    regular(backup/"originals.json")
    activity(root)
    # Bound inventory prevents collateral stops and detects detached processes.
    module=inventory_module(root);rows=module.processes(root);states=unit_states()
    need(all(r.get("role") in UNITS for r in rows),"UNMANAGED_APPLICATION_PROCESS")
    for role,current in states.items():
        matches=[r for r in rows if r["role"]==role]
        if current.get("ActiveState")=="active":
            need(current.get("SubState")=="running" and len(matches)==1
                 and matches[0]["pid"]==int(current.get("MainPID","0")),
                 "SERVICE_INVENTORY_PID_MISMATCH")
        else:
            need(current.get("ActiveState")=="inactive" and current.get("SubState")=="dead"
                 and current.get("MainPID")=="0" and not matches,
                 "SERVICE_STATE_REQUIRES_REVIEW")
    record=backup/"transaction.json"
    state["phase"]="ROLLING_BACK";write_json(record,state)
    try:
        call(["systemctl","--user","stop",*UNITS.values()])
        validate_stopped(unit_states(),module.processes(root))
        activity(root);release(root,allow_mixed=True)
        restore_files(root,backup,manifest)
        release(root)
        state["phase"]="ROLLBACK_STARTING";write_json(record,state)
        for unit in UNITS.values():call(["systemctl","--user","start",unit])
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                rows=module.inspect(root)["active_processes"]
                validate_running(unit_states(),rows)
                refresh_identities(root,rows,backup)
                verified=verify(root,installed=False)
                break
            except Exception:
                time.sleep(1)
        else:raise ValueError("ROLLBACK_STARTUP_VERIFICATION_FAILED")
        state.update(phase="ROLLED_BACK_PAUSED_VERIFIED",processes=verified)
        write_json(record,state)
        print(json.dumps(dict(status=state["phase"],backup=str(backup),
            controller_mode="PAUSED",production_execution_enabled=False),indent=2))
    except BaseException:
        state["phase"]="ROLLBACK_STOPPED_FOR_REVIEW"
        try:
            call(["systemctl","--user","stop",*UNITS.values()])
            validate_stopped(unit_states(),module.processes(root))
            state["failure_cleanup_services_stopped"]=True
        except Exception:state["failure_cleanup_services_stopped"]=False
        write_json(record,state)
        raise


def self_check():
    folder=Path(__file__).resolve().parent
    manifest=json.loads(regular(folder/"manifest.json").read_text())
    for name,expected in manifest["package_sha256"].items():
        need(sha(folder/name)==expected,"MAINTENANCE_PACKAGE_CHANGED")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["check","apply","verify","rollback"])
    parser.add_argument("--repo",type=Path,default=Path.cwd())
    parser.add_argument("--backup",type=Path)
    args=parser.parse_args();root=args.repo.resolve()
    self_check()
    if args.action=="rollback":
        need(args.backup is not None,"ROLLBACK_BACKUP_REQUIRED")
        rollback(root,args.backup);return
    if args.action=="apply":apply(root)
    elif args.action=="verify":
        rows=verify(root)
        print(json.dumps(dict(status="CLOSED_EXIT_DISPATCH_DEPLOYMENT_VERIFIED",
            processes=rows,controller_mode="PAUSED",production_execution_enabled=False),indent=2))
    else:
        rows=check(root)
        print(json.dumps(dict(status="CLOSED_EXIT_DISPATCH_MAINTENANCE_CHECKS_PASS",
            processes=rows,processes_signalled=False,applied=False,
            production_execution_enabled=False),indent=2))


if __name__=="__main__":
    try:main()
    except Exception as exc:
        message=str(exc)
        print(json.dumps(dict(status="STOPPED_FOR_REVIEW",
            reason=message if re.fullmatch("[A-Z][A-Z0-9_]{0,179}",message)
                   else type(exc).__name__,
            automatic_retry=False,production_execution_enabled=False)))
        raise SystemExit(1)
