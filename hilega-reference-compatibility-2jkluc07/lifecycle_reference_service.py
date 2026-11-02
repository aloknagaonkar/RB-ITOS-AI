"""Read-only capture/reference companion. Never submits orders."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

CLI_SHA = 'a6335cb61dbb94e8d19f392dc884135c58728d4b5868c48bf1f58708a97035de'


def check_package(repo, package):
    cli = package / "cli.py"
    if (cli.is_symlink() or not cli.is_file()
            or hashlib.sha256(cli.read_bytes()).hexdigest() != CLI_SHA):
        raise ValueError("PACKAGE_CLI_CHANGED")
    result = subprocess.run(
        [sys.executable, str(cli), "check", "--repo", str(repo)],
        text=True, capture_output=True, timeout=30,
    )
    if result.returncode:
        raise ValueError("PACKAGE_OR_RUNTIME_CHANGED")


def run_once(args, *, clock=lambda: datetime.now(timezone.utc)):
    from dotenv import dotenv_values
    from operational_lifecycle_review import exit_sequences
    from worker_lifecycle_handoff import capture_and_record
    from account_capture_provider import make_capture_provider
    from market_lab.hilega_production_account_adapter_v1 import Client, read_pin
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources

    pin = read_pin(args.pin_file)
    source = read_sources(args.application, args.adapter, pin["scope"])
    sequences = exit_sequences(source, args.journal)

    def provide():
        # Read the token only if the handoff requests a capture.
        if args.env_file.is_symlink() or not args.env_file.is_file():
            raise ValueError("REGULAR_ENV_FILE_REQUIRED")
        settings = dotenv_values(args.env_file)
        token = (settings.get("HILEGA_PRODUCTION_BROKER_READ_TOKEN")
                 or settings.get("UPSTOX_ACCESS_TOKEN"))
        if not token:
            raise ValueError("BROKER_READ_TOKEN_MISSING")
        client = Client(token)
        del token, settings
        return make_capture_provider(client, pin, clock=clock)()

    return capture_and_record(
        args.application, args.adapter, pin,
        journal=args.journal, exit_sequences=sequences,
        capture_provider=provide, clock=clock, mode="LIVE_CLOSED",
    )


def summary(result):
    return {key: result[key] for key in (
        "status", "database_modified", "account_capture_requested",
        "orders_sent_to_upstox", "production_execution_enabled",
    ) if key in result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--once", action="store_true")
    modes.add_argument("--watch", action="store_true")
    for name in (
        "repo", "package", "application", "adapter",
        "pin-file", "env-file", "journal",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        check_package(args.repo, args.package)
        for path in (
            args.application, args.adapter, args.pin_file,
            args.env_file, args.journal,
        ):
            if (path.is_symlink() or not path.is_file()
                    or any(p.is_symlink() for p in path.absolute().parents)):
                raise ValueError("REGULAR_EXISTING_SOURCE_REQUIRED")
        if args.check:
            print(json.dumps(dict(
                status="SERVICE_STARTUP_CHECK_PASS",
                database_opened=False, token_loaded=False,
                production_execution_enabled=False,
            )))
            return 0
        sys.path.insert(0, str(args.package))
        sys.path.insert(0, str(args.repo / "backend"))
        while True:
            # Recheck before each cycle; never reload modified code silently.
            check_package(args.repo, args.package)
            result = run_once(args)
            print(json.dumps(summary(result)), flush=True)
            if args.once:
                return 0
            time.sleep(60)
    except Exception as exc:
        print(json.dumps(dict(
            status="REFERENCE_SERVICE_STOPPED_ON_FAILURE",
            error_type=type(exc).__name__,
            commit_outcome="NOT_CERTIFIED_INSPECT_BEFORE_RESTART",
            orders_sent_to_upstox=False,
            production_execution_enabled=False,
        )), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
