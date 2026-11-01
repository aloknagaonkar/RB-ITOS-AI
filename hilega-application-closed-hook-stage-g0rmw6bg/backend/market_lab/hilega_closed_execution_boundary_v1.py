"""Closed execution-worker boundary and heartbeat. CLI never enables execution."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import tempfile
import time
import uuid

MODEL = 'HILEGA_CLOSED_EXECUTION_WORKER_HEALTH_V1'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def now():
    return datetime.now(timezone.utc)


def worker_tick(*, fixture_consumer=None):
    if fixture_consumer is None:
        return dict(status='EXECUTION_HANDOFF_CLOSED_IN_CODE',
                    production_execution_enabled=False, orders_sent_to_upstox=False,
                    entry_permission=False, application_database_opened=False,
                    token_loaded=False, fixture_consumer_used=False)
    # Python dependency injection for fixture tests only. CLI never supplies it.
    from fixture_cycle_journal_v2 import FixtureCycleJournalConsumerV2
    need(type(fixture_consumer) is FixtureCycleJournalConsumerV2
         and fixture_consumer.pin['scope'].startswith('FIXTURE:')
         and fixture_consumer.execution.mode == 'OFFLINE_FIXTURE',
         'EXACT_FIXTURE_WORKER_CONSUMER_REQUIRED')
    result = fixture_consumer.poll()
    need(result.get('production_execution_enabled') is False
         and result.get('orders_sent_to_upstox') is False,
         'FIXTURE_WORKER_AUTHORITY_CHANGED')
    return dict(result, fixture_consumer_used=True)


def private_parent(path):
    need(path.parent.is_dir() and not path.parent.is_symlink(),
         'EXISTING_PRIVATE_HEALTH_DIRECTORY_REQUIRED')
    info = path.parent.stat()
    need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
         'PRIVATE_HEALTH_DIRECTORY_REQUIRED')
    need(not path.is_symlink(), 'HEALTH_SYMLINK_REFUSED')


def write_health(path, row):
    path = Path(path)
    private_parent(path)
    if path.exists():
        info = path.stat()
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) & 0o077 == 0,
             'PRIVATE_REGULAR_HEALTH_FILE_REQUIRED')
        old = json.loads(path.read_text())
        need(old.get('model') == MODEL, 'HEALTH_TARGET_MODEL_MISMATCH')
    fd, temporary = tempfile.mkstemp(prefix='.closed-worker-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(row, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_health(path, *, as_of=None, max_age=15):
    path = Path(path)
    private_parent(path)
    info = path.stat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
         and stat.S_IMODE(info.st_mode) & 0o077 == 0 and info.st_size <= 65536,
         'PRIVATE_REGULAR_HEALTH_FILE_REQUIRED')
    row = json.loads(path.read_text())
    need(row.get('model') == MODEL, 'CLOSED_WORKER_HEALTH_MODEL_REQUIRED')
    expected = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    need(row.get('worker_sha256') == expected, 'CLOSED_WORKER_SOURCE_CHANGED')
    for key in ('production_execution_enabled', 'orders_sent_to_upstox',
                'entry_permission', 'application_database_opened', 'token_loaded'):
        need(row.get(key) is False, 'CLOSED_WORKER_AUTHORITY_CHANGED')
    stamp = datetime.fromisoformat(row['heartbeat_at'])
    current = as_of or now()
    need(stamp.tzinfo is not None and 0 <= (current-stamp).total_seconds() <= max_age,
         'CLOSED_WORKER_HEARTBEAT_STALE_OR_FUTURE')
    need(row.get('worker_state') == 'RUNNING', 'CLOSED_WORKER_NOT_RUNNING')
    return dict(status='CLOSED_WORKER_HEALTH_PASS', run_id=row['run_id'],
                ticks=row['ticks'], production_execution_enabled=False,
                orders_sent_to_upstox=False)


def run(args):
    need(1 <= args.interval <= 60, 'WORKER_INTERVAL_OUT_OF_RANGE')
    need(args.max_ticks is None or args.max_ticks > 0, 'POSITIVE_MAX_TICKS_REQUIRED')
    if args.health_file:
        private_parent(args.health_file)
    stopped = [False]
    def stop(signum, frame):
        stopped[0] = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    run_id = uuid.uuid4().hex
    fingerprint = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ticks = 0
    row = None
    state = 'FAILED'
    try:
        while not stopped[0]:
            result = worker_tick()  # Always closed; no CLI/env fixture injection.
            ticks += 1
            row = dict(result, model=MODEL, run_id=run_id, pid=os.getpid(),
                       worker_sha256=fingerprint, worker_state='RUNNING',
                       heartbeat_at=now().isoformat(), ticks=ticks)
            if args.health_file:
                write_health(args.health_file, row)
            print(json.dumps(row), flush=True)
            if args.once or args.max_ticks is not None and ticks >= args.max_ticks:
                state = 'COMPLETED'
                break
            # Short checks make TERM responsive without a long blocking sleep.
            until = time.monotonic()+args.interval
            while not stopped[0] and time.monotonic() < until:
                time.sleep(min(0.1, max(0, until-time.monotonic())))
        if stopped[0]:
            state = 'STOPPED'
    finally:
        if row is not None and args.health_file:
            write_health(args.health_file, dict(row, worker_state=state,
                                              heartbeat_at=now().isoformat()))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--once', action='store_true')
    group.add_argument('--watch', action='store_true')
    group.add_argument('--check', action='store_true')
    parser.add_argument('--health-file', type=Path)
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--max-ticks', type=int)
    parser.add_argument('--max-age', type=float, default=15)
    args = parser.parse_args()
    try:
        if args.check:
            need(args.health_file is not None, 'HEALTH_FILE_REQUIRED')
            print(json.dumps(validate_health(args.health_file, max_age=args.max_age)))
            return 0
        return run(args)
    except Exception as exc:
        reason = str(exc)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}', reason):
            reason = 'CLOSED_WORKER_INPUT_OR_HEALTH_INVALID'
        print(json.dumps(dict(status='BLOCKED', reason=reason,
                              production_execution_enabled=False,
                              orders_sent_to_upstox=False)), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
