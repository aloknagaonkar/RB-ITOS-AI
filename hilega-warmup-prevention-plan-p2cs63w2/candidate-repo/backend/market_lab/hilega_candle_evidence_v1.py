"""Opt-in provenance for decoded NIFTY candle inputs; no order transport."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .gateways import normalize_upstox_historical_candles

FLAG = "HILEGA_CANDLE_EVIDENCE_ENABLED"
MODEL = "HILEGA_CANDLE_INPUT_V1"
INSTRUMENT = "NSE_INDEX|Nifty 50"


def enabled():
    flag = os.getenv(FLAG, "0")
    if flag not in {"0", "1"}:
        raise ValueError("CANDLE_EVIDENCE_FLAG_INVALID")
    return flag == "1"


def root():
    path = Path(os.getenv(
        "HILEGA_CANDLE_EVIDENCE_ROOT",
        "data/live-observation/hilega-candle-input-v1",
    )).absolute()
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise ValueError("CANDLE_EVIDENCE_SYMLINK")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.stat().st_mode & 0o077:
        raise ValueError("CANDLE_EVIDENCE_PRIVATE_DIRECTORY_REQUIRED")
    return path


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def values(rows):
    return [
        dict(timestamp=c.timestamp.isoformat(),
             open=float(c.open), high=float(c.high),
             low=float(c.low), close=float(c.close),
             volume=getattr(c, "volume", None),
             open_interest=getattr(c, "open_interest", None))
        for c in rows
    ]


class CapturedCandles(list):
    def __init__(self, rows, reference):
        super().__init__(rows)
        self._reference = deepcopy(reference)

    @property
    def candle_evidence(self):
        return deepcopy(self._reference)


def reference(snapshot, digest):
    return {
        "model": MODEL, "snapshot_id": digest,
        **{k: snapshot[k] for k in (
            "instrument_key", "session_date",
            "request_started_at", "response_received_at",
        )},
    }


def capture(rows, body, session_date, started, received):
    if started.tzinfo is None or received.tzinfo is None or received < started:
        raise ValueError("CANDLE_EVIDENCE_TIME_INVALID")
    snapshot = dict(
        model=MODEL, instrument_key=INSTRUMENT,
        session_date=session_date.isoformat(),
        request_started_at=started.astimezone(timezone.utc).isoformat(),
        response_received_at=received.astimezone(timezone.utc).isoformat(),
        response={"status": body.get("status"),
                  "data": {"candles": body["data"]["candles"]}},
    )
    content = encoded(snapshot)
    digest = hashlib.sha256(content).hexdigest()
    path = root() / (digest + ".json")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise ValueError("CANDLE_EVIDENCE_EXISTING_FILE_CHANGED")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    directory_fd = os.open(root(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    batch = CapturedCandles(rows, reference(snapshot, digest))
    verify(batch)
    return batch


def verify(batch):
    if not isinstance(batch, CapturedCandles):
        raise ValueError("CANDLE_EVIDENCE_BATCH_REQUIRED")
    ref = batch.candle_evidence
    digest = ref.get("snapshot_id")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("CANDLE_EVIDENCE_ID_INVALID")
    path = root() / (digest + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("CANDLE_EVIDENCE_REGULAR_FILE_REQUIRED")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("CANDLE_EVIDENCE_HASH_MISMATCH")
    snapshot = json.loads(content)
    if (snapshot.get("model") != MODEL
            or snapshot.get("instrument_key") != INSTRUMENT
            or ref != reference(snapshot, digest)):
        raise ValueError("CANDLE_EVIDENCE_REFERENCE_MISMATCH")
    started = datetime.fromisoformat(snapshot["request_started_at"])
    received = datetime.fromisoformat(snapshot["response_received_at"])
    if started.tzinfo is None or received.tzinfo is None or received < started:
        raise ValueError("CANDLE_EVIDENCE_TIME_INVALID")
    original = normalize_upstox_historical_candles(
        INSTRUMENT, date.fromisoformat(snapshot["session_date"]),
        snapshot["response"],
    )
    if encoded(values(original)) != encoded(values(batch)):
        raise ValueError("CANDLE_EVIDENCE_ROWS_CHANGED")
    return ref


@contextmanager
def input_context(owner, rows):
    previous = getattr(owner, "_active_candle_evidence", None)
    ref = verify(rows) if enabled() else None
    owner._active_candle_evidence = ref
    try:
        yield
    finally:
        owner._active_candle_evidence = previous


def audit_fields(owner):
    ref = getattr(owner, "_active_candle_evidence", None)
    if ref is None:
        return {}
    return dict(
        candle_evidence=deepcopy(ref),
        audit_payload_created_at=datetime.now(timezone.utc).isoformat(),
    )
