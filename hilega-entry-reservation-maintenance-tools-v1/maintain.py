"""Deploy the VM-validated reservation patch while preserving closed execution."""
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

PIN="5800f8c5690b7750e1eed3846cc38a4845a42e07112ddf1e20aa058d48acf553"
INVENTORY_BLOB="1504472bd17c5d062321e138627d1dc6dce0f355"
UNITS={"worker":"hilega-worker.service","api":"hilega-api.service",
       "production-source-worker":"hilega-production-source-worker.service"}
IDENTITIES="backups/hilega-preparation-activation-cvtlkibq/maintenance.json"
TARGETS={
 "backend/market_lab/hilega_preparation_runtime_v1/atomic_binding.py",
 "backend/market_lab/hilega_preparation_runtime_v1/cash_reservation.py",
 "check-preparation-paused.py"}


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
    need(value.get("local_cash_reservation_count",0)==0,
         "LOCAL_RESERVATION_REQUIRES_REVIEW")


def release(root,*,installed=False):
    package=regular(root/"hilega-entry-reservation-integration-tools-v1/manifest.json").parent
    need(sha(package/"manifest.json")==PIN,"INTEGRATION_MANIFEST_CHANGED")
    manifest=json.loads((package/"manifest.json").read_text())
    need(set(manifest["runtime_targets"])==TARGETS,"UNEXPECTED_RUNTIME_TARGETS")
    for name,expected in manifest["package_sha256"].items():
        need(sha(package/name)==expected,"STAGED_PACKAGE_CHANGED")
    for name,expected in manifest["baseline_sha256"].items():
        path=root/name
        if installed and name in manifest["runtime_targets"]:
            expected=manifest["package_sha256"][manifest["runtime_targets"][name]]
        if expected is None:
            need(not path.exists() and not path.is_symlink(),"NEW_TARGET_ALREADY_EXISTS")
        else:need(sha(path)==expected,"INSTALLED_SOURCE_CHANGED")
    reports=sorted(package.glob("RESERVATION_INTEGRATION_REGRESSION-*.json"))
    need(bool(reports),"VM_REGRESSION_REPORT_REQUIRED")
    proof=json.loads(regular(reports[-1]).read_text())
    need(proof.get("status")=="PASS" and proof.get("pytest_exit_code")==0
         and proof.get("local_unit_tests_passed")==14
         and proof.get("package_manifest_sha256")==PIN
         and proof.get("baseline_sha256")==manifest["baseline_sha256"]
         and all(proof.get(k) is False for k in (
             "applied","services_restarted","database_migration_performed",
             "production_execution_enabled")),"VM_REGRESSION_PROOF_INVALID")
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


def verify(root):
    release(root,installed=True)
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
    backup=Path(tempfile.mkdtemp(prefix="hilega-entry-reservation-maintenance-",dir=backups))
    record=backup/"transaction.json"
    state=dict(phase="PREPARED",previous_processes=rows,backup=str(backup),
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
            entry_allocation_fraction="0.50")
        state.pop("starting_unit",None)
        write_json(record,state)
        print(json.dumps(dict(state,status="ENTRY_RESERVATION_DEPLOYED_PAUSED_VERIFIED"),indent=2))
    except BaseException:
        state["failure_after_phase"]=state["phase"]
        state["phase"]="STOPPED_FOR_REVIEW_NO_AUTOMATIC_RETRY"
        write_json(record,state)
        print(json.dumps(dict(status=state["phase"],backup=str(backup),
            failure_after_phase=state["failure_after_phase"],
            starting_unit=state.get("starting_unit"),
            automatic_retry=False,production_execution_enabled=False)),flush=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["check","apply","verify"])
    parser.add_argument("--repo",type=Path,default=Path.cwd())
    args=parser.parse_args();root=args.repo.resolve()
    if args.action=="apply":apply(root)
    elif args.action=="verify":
        rows=verify(root)
        print(json.dumps(dict(status="ENTRY_RESERVATION_DEPLOYMENT_VERIFIED",
            processes=rows,controller_mode="PAUSED",production_execution_enabled=False),indent=2))
    else:
        rows=check(root)
        print(json.dumps(dict(status="ENTRY_RESERVATION_MAINTENANCE_CHECKS_PASS",
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
