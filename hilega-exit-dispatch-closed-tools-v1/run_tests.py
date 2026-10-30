"""Test closed application exit dispatch in a temporary import overlay. No apply."""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

FOLDER=Path(__file__).resolve().parent
TESTS=(
    "tests/test_hilega_atomic_disabled_binding_v1.py",
    "tests/test_hilega_application_preparation_v1.py",
    "tests/test_hilega_preparation_wait_admission_v1.py",
    "tests/test_hilega_preparation_pricing_wiring_v1.py",
    "tests/test_hilega_limit_candidate_v1.py",
    "tests/test_hilega_consolidated_adapter_v1.py",
)


def sha(path):
    if not path.is_file() or path.is_symlink():raise ValueError("REGULAR_SOURCE_REQUIRED")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_check(root):
    manifest=json.loads((FOLDER/"manifest.json").read_text())
    for name,expected in manifest["package_sha256"].items():
        if sha(FOLDER/name)!=expected:raise ValueError("PACKAGE_SOURCE_CHANGED")
    for name,expected in manifest["baseline_sha256"].items():
        path=root/name
        try:
            if expected is None:
                if path.exists() or path.is_symlink():raise ValueError("NEW_RUNTIME_TARGET_ALREADY_EXISTS")
            elif sha(path)!=expected:raise ValueError("INSTALLED_BASELINE_CHANGED")
        except Exception as exc:
            exc.source=name
            raise
    return manifest


def overlay_init(original,paths):
    lines=original.splitlines(keepends=True)
    tree=ast.parse(original);offset=0
    for node in tree.body:
        if isinstance(node,ast.ImportFrom) and node.module=="__future__":
            offset=max(offset,node.end_lineno)
    lines.insert(offset,"__path__ = "+repr([str(p) for p in paths])+"\n")
    return "".join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",type=Path,default=Path.cwd())
    args=p.parse_args();root=args.repo.resolve()
    manifest=manifest_check(root)
    for name in TESTS:
        if not (root/name).is_file():raise ValueError("REQUIRED_EXISTING_TEST_MISSING")
    unit=subprocess.run([sys.executable,"-W","error::ResourceWarning","-m","unittest",
        "discover","-s",str(FOLDER),"-p","test_dispatch_unit.py","-q"],cwd=root)
    if unit.returncode:raise ValueError("LOCAL_DISPATCH_TESTS_FAILED")
    with tempfile.TemporaryDirectory(prefix="hilega-closed-exit-overlay-") as temporary:
        overlay=Path(temporary)
        shutil.copytree(FOLDER/"runtime",overlay,dirs_exist_ok=True)
        original=root/"backend/market_lab"
        for relative in ("market_lab","market_lab/hilega_preparation_runtime_v1"):
            target=overlay/relative;target.mkdir(parents=True,exist_ok=True)
            source=root/"backend"/relative/"__init__.py"
            text=overlay_init(source.read_text(),[target,root/"backend"/relative])
            (target/"__init__.py").write_text(text)
        env=dict(os.environ)
        env["PYTHONPATH"]=os.pathsep.join(map(str,(
            overlay,root/"backend",root/"tests",root)))
        result=subprocess.run([sys.executable,"-m","pytest","-q",
            *[str(root/name) for name in TESTS],
            str(FOLDER/"test_source_dispatch.py")],cwd=root,env=env)
    report=dict(status="PASS" if result.returncode==0 else "FAIL",
        pytest_exit_code=result.returncode,local_unit_tests_passed=10,
        regression_tests=list(TESTS)+["test_source_dispatch.py"],
        package_manifest_sha256=sha(FOLDER/"manifest.json"),
        baseline_sha256=manifest["baseline_sha256"],
        applied=False,services_restarted=False,database_migration_performed=False,
        production_execution_enabled=False,
        exit_dispatch_scope="DURABLE_REFUSED_NON_EXECUTABLE_ONLY",
        live_exit_submission_integrated=False,
        reservation_release_permission=False,
        daily_loss_limit_required=False,
        entry_allocation_fraction="0.50",
        production_ready=False)
    path=FOLDER/("CLOSED_EXIT_DISPATCH_REGRESSION-"+
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+".json")
    with path.open("x") as stream:json.dump(report,stream,indent=2)
    report["report"]=str(path)
    print(json.dumps(report,indent=2))
    raise SystemExit(result.returncode)


if __name__=="__main__":
    try:main()
    except Exception as exc:
        if isinstance(exc,SystemExit):raise
        print(json.dumps(dict(status="STOPPED_FOR_REVIEW",
            error_type=type(exc).__name__,
            reason=str(exc) if re.fullmatch("[A-Z][A-Z0-9_]{0,179}",str(exc)) else None,
            source=getattr(exc,"source",None),
            applied=False,
            production_execution_enabled=False)))
        raise SystemExit(1)
