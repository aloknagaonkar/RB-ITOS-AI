"""Opt-in, append-only acquisition evidence for observation-only Hilega-Milega.

Capture records the *response visible at each call*, including empty responses.
SHA-256 chaining detects accidental mutation; this is not tamper-proof WORM storage.
Playback never calls a broker and requires identical source-call ordering.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from .domain import HistoricalCandle, IST
from .live_option_minute_source_v1 import CompletedOptionMinute

MODEL = "HILEGA_MARKET_EVIDENCE_V1"
ZERO_HASH = "0" * 64


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def serial(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return serial(value.model_dump(mode="json"))
    if is_dataclass(value):
        return serial(asdict(value))
    if isinstance(value, (list, tuple)):
        return [serial(x) for x in value]
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("UNSUPPORTED_EVIDENCE_TYPE:" + type(value).__name__)


def verify_journal(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise ValueError("EVIDENCE_FILE_MISSING")
    previous = ZERO_HASH
    output = []
    responses = {}
    with path.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            try:
                row = json.loads(raw)
                body = {k: v for k, v in row.items() if k != "record_hash"}
                if body.get("model") != MODEL or body.get("sequence") != number:
                    raise ValueError("EVIDENCE_SEQUENCE_OR_MODEL_INVALID")
                if body.get("previous_hash") != previous:
                    raise ValueError("EVIDENCE_CHAIN_BROKEN")
                want = hashlib.sha256(canonical(body)).hexdigest()
                if want != row.get("record_hash"):
                    raise ValueError("EVIDENCE_DIGEST_MISMATCH")
                previous = want
                if row.get("response_ref") is not None:
                    ref = row["response_ref"]
                    if ref not in responses:
                        raise ValueError("EVIDENCE_RESPONSE_REFERENCE_MISSING")
                    row["response"] = responses[ref]
                elif row.get("kind") in {"underlying", "warmup", "option", "contracts"} and row.get("status") == "OK":
                    digest = hashlib.sha256(canonical(row["response"])).hexdigest()
                    responses[digest] = row["response"]
                output.append(row)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"EVIDENCE_INVALID_LINE_{number}:{exc}") from exc
    return output


class EvidenceJournalV1:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # OS lock prevents two live workers from interleaving hash-chain events.
        self.fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            existing = verify_journal(self.path)
        except Exception:
            os.close(self.fd)
            self.fd = None
            raise
        self.sequence = len(existing)
        self.previous_hash = existing[-1]["record_hash"] if existing else ZERO_HASH
        self._response_hashes = {
            hashlib.sha256(canonical(x["response"])).hexdigest()
            for x in existing if x["kind"] in {"underlying", "warmup", "option", "contracts"}
            and x["status"] == "OK"
        }

    def append(self, kind: str, args: dict, response: Any = None, *, status: str = "OK") -> None:
        self.sequence += 1
        body = {
            "model": MODEL, "sequence": self.sequence,
            "acquired_utc": datetime.now(timezone.utc).isoformat(),
            "kind": kind, "args": serial(args), "status": status,
            "previous_hash": self.previous_hash,
        }
        encoded_response = serial(response)
        if kind in {"underlying", "warmup", "option", "contracts"} and status == "OK":
            response_hash = hashlib.sha256(canonical(encoded_response)).hexdigest()
            if response_hash in self._response_hashes:
                body["response_ref"] = response_hash
            else:
                body["response"] = encoded_response
                self._response_hashes.add(response_hash)
        else:
            body["response"] = encoded_response
        digest = hashlib.sha256(canonical(body)).hexdigest()
        row = dict(body, record_hash=digest)
        raw = canonical(row) + b"\n"
        if os.write(self.fd, raw) != len(raw):
            raise OSError("EVIDENCE_SHORT_WRITE")
        os.fsync(self.fd)
        self.previous_hash = digest

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class RecordingHilegaSourcesV1:
    """Record only data supplied to this strategy; never capture credentials."""
    def __init__(self, upstream: Any, journal: EvidenceJournalV1) -> None:
        self.upstream = upstream
        self.journal = journal

    def close(self) -> None:
        self.journal.close()

    def tick(self, now: datetime) -> None:
        self.journal.append("tick", {"now": now.astimezone(IST).isoformat()})

    def _call(self, kind: str, args: dict, callback):
        try:
            rows = callback()
        except Exception as exc:
            # Error types only, never broker exception strings (which may contain secrets).
            self.journal.append(kind, args, {"error_type": type(exc).__name__}, status="ERROR")
            raise
        self.journal.append(kind, args, rows)
        return rows

    def warmup_candles(self, session_date: date, cache_root: Path):
        from .hilega_milega_historical_replay_v1 import UNDERLYING, load_or_fetch_1m
        return self._call("warmup", {"date": session_date.isoformat()},
                          lambda: load_or_fetch_1m(self.upstream, underlying=UNDERLYING,
                                                    session_date=session_date, cache_root=cache_root,
                                                    refresh_cache=False))

    def nifty_intraday_1m(self, *, now: datetime | None = None):
        return self._call("underlying", {"now": now.astimezone(IST).isoformat() if now else None},
                          lambda: self.upstream.nifty_intraday_1m(now=now))

    def option_contracts(self, underlying: str, expiry: date):
        return self._call("contracts", {"underlying": underlying, "expiry": expiry.isoformat()},
                          lambda: self.upstream.option_contracts(underlying, expiry))

    def option_intraday_1m(self, instrument_key: str):
        return self._call("option", {"instrument_key": instrument_key},
                          lambda: self.upstream.option_intraday_1m(instrument_key))


class PlaybackHilegaSourcesV1:
    """Strict, completely offline replay of the actual recorded source-call tape."""
    def __init__(self, path: str | Path):
        self.rows = verify_journal(path)
        self.index = 0
        self.process_start = None

    def _read(self, kind: str, args: dict):
        if self.index >= len(self.rows):
            raise ValueError(f"EVIDENCE_EXHAUSTED_EXPECTED_{kind}")
        row = self.rows[self.index]
        if row["kind"] != kind or row["args"] != serial(args):
            raise ValueError(f"EVIDENCE_CALL_DIVERGENCE_AT_{self.index+1}:expected_{kind}")
        self.index += 1
        if row["status"] != "OK":
            raise ValueError(f"EVIDENCE_RECORDED_UPSTREAM_ERROR_AT_{self.index}")
        return row["response"]

    def next_tick(self) -> datetime | None:
        if self.index == len(self.rows):
            return None
        row = self.rows[self.index]
        self.process_start = None
        while row["kind"] == "process_start":
            self.process_start = self._read("process_start", row["args"])
            if self.index == len(self.rows):
                raise ValueError("EVIDENCE_TRAILING_PROCESS_START_WITHOUT_TICK")
            row = self.rows[self.index]
        if row["kind"] != "tick":
            raise ValueError(f"EVIDENCE_UNCONSUMED_SOURCE_EVENT_AT_{self.index+1}")
        self._read("tick", row["args"])
        return datetime.fromisoformat(row["args"]["now"])

    def warmup_candles(self, session_date: date, cache_root: Path):
        return [HistoricalCandle.model_validate(r) for r in
                self._read("warmup", {"date": session_date.isoformat()})]

    def nifty_intraday_1m(self, *, now: datetime | None = None):
        return [HistoricalCandle.model_validate(r) for r in
                self._read("underlying", {"now": now.astimezone(IST).isoformat() if now else None})]

    def option_contracts(self, underlying: str, expiry: date):
        return self._read("contracts", {"underlying": underlying, "expiry": expiry.isoformat()})

    def option_intraday_1m(self, instrument_key: str):
        return [CompletedOptionMinute(
            instrument_key=r["instrument_key"], timestamp=datetime.fromisoformat(r["timestamp"]),
            open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"])
            for r in self._read("option", {"instrument_key": instrument_key})]

    def assert_consumed(self) -> None:
        if self.index != len(self.rows):
            raise ValueError(f"EVIDENCE_NOT_FULLY_CONSUMED:{len(self.rows)-self.index}")
