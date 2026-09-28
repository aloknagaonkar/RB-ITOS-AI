#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import importlib.util
from pathlib import Path
import tempfile

from market_lab.domain import IST
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1


CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
SESSION = "2026-08-25"


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 1.0


class UnusedSources:
    pass


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def row_to_candle(ts: str, row: dict) -> Candle:
    d = datetime.fromisoformat(ts)
    if d.tzinfo is None:
        d = d.replace(tzinfo=IST)
    return Candle(
        timestamp=d.astimezone(IST),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
    )


def main():
    print("MIDPOINT M3B.1 — 2026-08-25 CANONICAL FAMILY-B PARITY")
    print("=" * 100)

    c = import_module(CANON, "canonical_b_m3b1")

    _, framework = c.load_framework()
    _, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    if dup_conflicts != 0:
        raise SystemExit(f"STOP: underlying duplicate conflicts={dup_conflicts}")

    u = underlying.get(SESSION)
    fut = futures.get(SESSION)
    if not u or not fut:
        raise SystemExit("STOP: canonical 2026-08-25 underlying/futures data unavailable")

    canonical = []
    for e in framework:
        if e["session_date"] != SESSION:
            continue
        b = c.family_b_for_event(e, u, fut)
        if b:
            canonical.append(b)

    canonical_bear = [
        x for x in canonical
        if x["direction"] == "BEARISH"
        and x["family"] == "B_DELAYED_FULL_CANDIDATE_A"
    ]
    if len(canonical_bear) != 1:
        raise SystemExit(
            f"STOP: expected one canonical bearish B, found {len(canonical_bear)}"
        )

    expected = canonical_bear[0]
    candles = {ts: row_to_candle(ts, row) for ts, row in u.items()}

    with tempfile.TemporaryDirectory() as td:
        coord = MidpointLiveShadowCoordinatorV1(
            market_sources=UnusedSources(),
            audit_path=Path(td) / "audit.jsonl",
        )
        coord._reset_session(date.fromisoformat(SESSION))

        underlying_by_ts = {
            candle.timestamp.replace(second=0, microsecond=0): candle
            for candle in candles.values()
        }

        for ts_s in sorted(u):
            if not c.is_trusted(ts_s):
                continue
            frow = fut.get(ts_s)
            if frow is None:
                continue

            ts = datetime.fromisoformat(ts_s)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            ts = ts.astimezone(IST).replace(second=0, microsecond=0)

            raw_diff = float(frow["diff"])

            coord._process_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
                futures_close=raw_diff,
                futures_vwap=0.0,
                underlying_by_ts=underlying_by_ts,
            )
            coord.state.processed_minutes.add(ts)

        rows = coord.engine.journal.read_all()

        live_entries = [
            r for r in rows
            if r["event_type"] == "B_ENTRY" and r["direction"] == "BEARISH"
        ]
        assert len(live_entries) == 1, len(live_entries)
        actual = live_entries[0]

        boundaries = [
            r for r in rows
            if r["event_type"] == "BOUNDARY_BREAK" and r["direction"] == "BEARISH"
        ]
        assert boundaries, "missing bearish boundary break"
        boundary = boundaries[0]

        assert actual["event_timestamp"] == expected["entry_timestamp"]
        assert boundary["event_timestamp"] == expected["origin_timestamp"]
        assert actual["direction"] == expected["direction"]
        assert abs(actual["reference_high"] - float(expected["reference_high"])) < 1e-9
        assert abs(actual["midpoint"] - float(expected["reference_midpoint"])) < 1e-9
        assert abs(actual["reference_low"] - float(expected["reference_low"])) < 1e-9

        actual_raw_diff = float(actual["futures_price"]) - float(actual["futures_vwap"])
        expected_raw_diff = float(expected["entry_fut_vwap"])
        assert abs(actual_raw_diff - expected_raw_diff) < 1e-9

        delay = (
            datetime.fromisoformat(actual["event_timestamp"])
            - datetime.fromisoformat(boundary["event_timestamp"])
        ).total_seconds() / 60.0
        assert delay == float(expected["delay_minutes"])

        print("PASS: canonical bearish Family B detected exactly once")
        print("PASS: boundary timestamp =", boundary["event_timestamp"])
        print("PASS: B entry timestamp =", actual["event_timestamp"])
        print("PASS: direction =", actual["direction"])
        print("PASS: delay_minutes =", delay)
        print("PASS: reference_high =", actual["reference_high"])
        print("PASS: reference_midpoint =", actual["midpoint"])
        print("PASS: reference_low =", actual["reference_low"])
        print("PASS: raw futures-VWAP diff =", actual_raw_diff)
        print("PASS: no nearest-minute substitution")
        print("PASS: no interpolation")
        print("PASS: observation-only parity run")


if __name__ == "__main__":
    main()
