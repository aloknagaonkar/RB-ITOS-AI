"""Standalone lifecycle reference review. No order transport or service hook."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from account_capture_provider import make_capture_provider
from worker_lifecycle_handoff import capture_and_record
from market_lab.hilega_production_account_adapter_v1 import Client, read_pin
from market_lab.hilega_production_simulator_bridge_v1 import (
    verified_records, accepted, POLICY, VERSION,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def private_token(path):
    p = Path(path).absolute()
    need(not any(parent.is_symlink() for parent in p.parents),
         "TOKEN_SYMLINK_PARENT_FORBIDDEN")
    parent = p.parent.stat()
    need(parent.st_uid == os.getuid()
         and not stat.S_IMODE(parent.st_mode) & 0o077,
         "TOKEN_DIRECTORY_MUST_BE_PRIVATE")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode)
             and info.st_uid == os.getuid()
             and not stat.S_IMODE(info.st_mode) & 0o077
             and 0 < info.st_size <= 16384,
             "TOKEN_FILE_MUST_BE_PRIVATE_REGULAR_FILE")
        token = stream.read().rstrip("\r\n")
    need(bool(token) and "\r" not in token and "\n" not in token,
         "TOKEN_CONTENT_INVALID")
    return token


def exit_sequences(source, journal):
    requests = [json.loads(raw) for _, _, raw in source["requests"]]
    wanted = {
        row["signal_id"] for row in requests
        if row["draft"]["body"]["transaction_type"] == "SELL"
    }
    if not wanted:
        return []
    found = {}
    for record in verified_records(journal):
        payload = record.get("payload") or {}
        if (payload.get("policy_id") != POLICY
                or payload.get("strategy_version") != VERSION):
            continue
        events = accepted(record)
        for event in events:
            if event["id"] not in wanted:
                continue
            need(len(events) == 1 and event["role"] == "EXIT",
                 "SINGLE_EXIT_BOUNDARY_REQUIRED")
            need(event["id"] not in found, "DUPLICATE_EXIT_JOURNAL_REFERENCE")
            found[event["id"]] = record["sequence"]
    need(set(found) == wanted, "CONFIRMED_EXIT_JOURNAL_REFERENCE_MISSING")
    return sorted(found.values())


def run_reference_review(
    application, adapter, *, pin_file, token_file, journal,
    clock=lambda: datetime.now(timezone.utc),
):
    pin = read_pin(pin_file)
    source = read_sources(application, adapter, pin["scope"])
    sequences = exit_sequences(source, journal)

    def provide():
        # Credentials and Client construction are deferred until a bound
        # entry actually requires a capture.
        client = Client(private_token(token_file))
        return make_capture_provider(client, pin, clock=clock)()

    return capture_and_record(
        application, adapter, pin, journal=journal,
        exit_sequences=sequences, capture_provider=provide,
        clock=clock, mode="LIVE_CLOSED",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("application", "adapter", "pin-file", "token-file", "journal"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_reference_review(
            args.application, args.adapter,
            pin_file=args.pin_file, token_file=args.token_file,
            journal=args.journal,
        )
    except Exception as exc:
        # Never print provider text, credentials or arbitrary exception values.
        print(json.dumps(dict(
            status="LIFECYCLE_OPERATION_FAILED",
            error_type=type(exc).__name__,
            commit_outcome="NOT_CERTIFIED_INSPECT_BEFORE_RETRY",
            orders_sent_to_upstox=False,
            production_execution_enabled=False,
        )))
        return 2
    summary = {key: result[key] for key in (
        "status", "account_capture_requested", "database_modified",
        "orders_sent_to_upstox", "production_execution_enabled",
    ) if key in result}
    summary["running_service_hook_installed"] = False
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
