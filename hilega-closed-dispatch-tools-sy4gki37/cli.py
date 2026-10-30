"""Read-only closed dispatch review. No submission action."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

FOLDER = Path(__file__).resolve().parent

def need(ok, reason):
    if not ok:
        raise ValueError(reason)

def fingerprint(path):
    need(path.is_file() and not path.is_symlink()
         and not any(p.is_symlink() for p in path.parents),
         "REGULAR_PINNED_FILE_REQUIRED")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify_package(root):
    manifest = FOLDER / "manifest.json"
    value = json.loads(manifest.read_text())
    need(value.get("model") == "HILEGA_CLOSED_DISPATCH_PACKAGE_V1",
         "PACKAGE_MODEL_INVALID")
    for base, entries in (
        (FOLDER, value["package_sha256"]),
        (root, value["runtime_sha256"]),
    ):
        for name, expected in entries.items():
            relative = Path(name)
            need(not relative.is_absolute() and ".." not in relative.parts,
                 "MANIFEST_PATH_INVALID")
            need(fingerprint(base / relative) == expected,
                 "PACKAGE_OR_RUNTIME_HASH_MISMATCH")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("package-check", "check"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.repo.resolve()
    verify_package(root)
    if args.action == "package-check":
        return dict(
            status="CLOSED_DISPATCH_PACKAGE_CHECK_PASS",
            application_database_accessed=False,
            broker_reads_performed=False,
            database_modified=False,
            production_execution_enabled=False,
        )

    sys.path.insert(0, str(root / "backend"))
    from market_lab.hilega_production_account_adapter_v1 import read_pin
    pin_path = Path.home() / "hilega-private/upstox-account-pin.json"
    pin = read_pin(pin_path)
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "LIVE_ACCOUNT_PIN_REQUIRED")
    spec = importlib.util.spec_from_file_location(
        "packaged_closed_dispatch", FOLDER / "closed_entry_dispatch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.dispatch_closed(
        root / "data/research/hilega-production-workspace/sim.sqlite",
        root / "data/research/hilega-broker-adapter-closed/adapter.sqlite",
        pin, as_of=datetime.now(timezone.utc).isoformat(),
    )
    need(read_pin(pin_path) == pin, "ACCOUNT_PIN_CHANGED_DURING_REVIEW")
    return result

if __name__ == "__main__":
    try:
        print(json.dumps(main(), indent=2))
    except Exception as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", reason):
            reason = "SOURCE_OR_PACKAGE_REVIEW_REQUIRED"
        print(json.dumps(dict(
            status="CLOSED_DISPATCH_CLI_STOPPED_FOR_REVIEW",
            reason=reason,
            database_modified=False,
            broker_reads_performed=False,
            entry_permission=False,
            orders_sent=False,
            production_execution_enabled=False,
            reservation_release_permission=False,
            production_ready=False,
        ), indent=2))
        raise SystemExit(1)
