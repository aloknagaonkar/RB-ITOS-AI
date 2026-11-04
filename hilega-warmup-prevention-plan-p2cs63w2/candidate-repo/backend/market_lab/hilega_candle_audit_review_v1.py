"""Offline review of live decision-to-candle snapshot links."""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

from .domain import IST
from .gateways import normalize_upstox_historical_candles
from .hilega_candle_evidence_v1 import MODEL, INSTRUMENT, reference
from .hilega_production_simulator_bridge_v1 import verified_records


def aware(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed


def check_record(record, root, session):
    p = record["payload"]
    ref = p["candle_evidence"]
    digest = ref["snapshot_id"]
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("SNAPSHOT_ID_INVALID")
    path = root / (digest + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("SNAPSHOT_REGULAR_FILE_REQUIRED")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    snapshot = json.loads(raw)
    if (snapshot.get("model") != MODEL
            or snapshot.get("instrument_key") != INSTRUMENT
            or ref != reference(snapshot, digest)
            or snapshot["session_date"] != session.isoformat()):
        raise ValueError("SNAPSHOT_REFERENCE_MISMATCH")

    rows = normalize_upstox_historical_candles(
        INSTRUMENT, session, snapshot["response"]
    )
    minute_at = aware(p["minute_timestamp"])
    label = aware(p["bar_timestamp"])
    decision = aware(p["decision_timestamp"])
    received = aware(ref["response_received_at"])
    minute = [c for c in rows if c.timestamp == minute_at]
    bucket = [
        [c for c in rows if c.timestamp == label + timedelta(minutes=i)]
        for i in range(5)
    ]
    exact = len(minute) == 1 and all(len(xs) == 1 for xs in bucket)
    checks = {
        "snapshot_integrity": True,
        "exact_minutes": exact,
        "five_minute_boundary": (
            decision == label + timedelta(minutes=5)
            and decision == minute_at + timedelta(minutes=1)
            and decision.astimezone(IST).date() == session
            and label.second == label.microsecond == 0
            and label.astimezone(IST).minute % 5 == 0
        ),
        "receipt_and_audit_times": (
            aware(ref["request_started_at"]) <= received
            <= aware(p["audit_payload_created_at"])
            and decision <= received
        ),
        "observation_only": (
            p.get("execution_enabled") is False
            and p.get("observation_only") is True
        ),
    }
    def equal(a, b):
        a, b = float(a), float(b)
        return math.isfinite(a) and math.isfinite(b) and abs(a-b) <= 1e-7

    if exact:
        xs = [items[0] for items in bucket]
        expected = dict(
            open=xs[0].open, high=max(c.high for c in xs),
            low=min(c.low for c in xs), close=xs[-1].close,
        )
        checks["minute_ohlc"] = all(
            equal(p["minute_ohlcv"][k], getattr(minute[0], k))
            for k in expected
        )
        checks["five_minute_ohlc"] = all(
            equal(p["price_ema_frame"][k], expected[k]) for k in expected
        )
    return dict(
        sequence=record["sequence"], decision_timestamp=p["decision_timestamp"],
        snapshot_id=digest, checks=checks, passed=all(checks.values()),
    )


def review(journal, root, session):
    root = Path(root).absolute()
    for part in (*reversed(root.parents), root):
        if part.is_symlink():
            raise ValueError("EVIDENCE_DIRECTORY_SYMLINK")
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError("PRIVATE_EVIDENCE_DIRECTORY_REQUIRED")

    results = []
    unlinked = 0
    for record in verified_records(Path(journal)):
        if record.get("stage") != "DIRECTIONAL_DECISION":
            continue
        p = record["payload"]
        if (record.get("status") != "PROCESSED"
                or p.get("reconstructed") is not False
                or p.get("strategy_id") != "HILEGA_V2_ALIGNMENT_DUAL_EXIT"):
            continue
        if aware(p["decision_timestamp"]).astimezone(IST).date() != session:
            continue
        if not p.get("candle_evidence"):
            unlinked += 1
            continue
        try:
            results.append(check_record(record, root, session))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            results.append(dict(
                sequence=record["sequence"], passed=False,
                error_type=type(exc).__name__,
            ))

    failed = sum(not r["passed"] for r in results)
    status = "FAILED" if failed else ("PASS" if results else "WAITING")
    return dict(
        model="HILEGA_CANDLE_AUDIT_REVIEW_V1",
        scope="LINKED_LIVE_DECISION_INPUTS_ONLY",
        assessed_at=datetime.now(timezone.utc).isoformat(),
        session=session.isoformat(), status=status,
        linked_decisions=len(results), unlinked_decisions=unlinked,
        failed_decisions=failed, decisions=results,
        production_ready=False, orders_sent_by_review=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=Path(
        "data/live-observation/hilega-directional-v1/step-audit.jsonl"))
    parser.add_argument("--capture-root", type=Path, default=Path(
        "data/live-observation/hilega-candle-input-v1"))
    parser.add_argument("--session", type=date.fromisoformat,
                        default=datetime.now(IST).date())
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = review(args.journal, args.capture_root, args.session)
        # Exclusive creation: never replace an existing report or source file.
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT |
                     os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        summary = {k: v for k, v in report.items() if k != "decisions"}
        summary.update(report=str(args.report), latest=report["decisions"][-3:])
        print(json.dumps(summary, indent=2))
        return {"PASS": 0, "WAITING": 2, "FAILED": 1}[report["status"]]
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps(dict(status="ERROR", error_type=type(exc).__name__,
                              production_ready=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
