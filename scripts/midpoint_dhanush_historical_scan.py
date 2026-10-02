#!/usr/bin/env python3
"""Research-only historical scan for the DHANUSH midpoint pattern.

Frozen V1 definition:
- origin is an observed B or E entry and its original midpoint;
- completed 5-minute candles only;
- approach zone is exact midpoint +/- 10 NIFTY points;
- attempts are distinct episodes separated by a completed 5-minute candle
  whose full directional extreme moves back outside the approach zone;
- attempts one and two must remain on the origin side at every completed close;
- attempt three confirms when a completed close crosses the exact midpoint;
- bullish and bearish origins are symmetric.

No live files, configuration, audits, orders, or quantities are modified.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")
OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-dhanush-v1"
)


def _import(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class FiveMinuteBar:
    start: datetime
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class Attempt:
    number: int
    start_timestamp: datetime
    last_timestamp: datetime
    closest_distance: float
    confirmed_cross_timestamp: datetime | None = None
    confirmed_cross_close: float | None = None


@dataclass
class DhanushDetector:
    midpoint: float
    origin_direction: str
    zone_points: float = 10.0
    attempts: list[Attempt] = field(default_factory=list)
    active: Attempt | None = None
    failed_early_cross: bool = False

    def _reaches_zone(self, bar: FiveMinuteBar) -> bool:
        if self.origin_direction == "BEARISH":
            return bar.high >= self.midpoint - self.zone_points
        return bar.low <= self.midpoint + self.zone_points

    def _moves_away(self, bar: FiveMinuteBar) -> bool:
        if self.origin_direction == "BEARISH":
            return bar.high < self.midpoint - self.zone_points
        return bar.low > self.midpoint + self.zone_points

    def _crossed(self, bar: FiveMinuteBar) -> bool:
        if self.origin_direction == "BEARISH":
            return bar.close > self.midpoint
        return bar.close < self.midpoint

    def _distance(self, bar: FiveMinuteBar) -> float:
        extreme = bar.high if self.origin_direction == "BEARISH" else bar.low
        return abs(extreme - self.midpoint)

    def observe(self, bar: FiveMinuteBar) -> bool:
        """Return True exactly once when attempt three confirms."""
        if self.failed_early_cross:
            return False
        reaches = self._reaches_zone(bar)
        if self.active is None and reaches:
            self.active = Attempt(
                number=len(self.attempts) + 1,
                start_timestamp=bar.timestamp,
                last_timestamp=bar.timestamp,
                closest_distance=self._distance(bar),
            )
            self.attempts.append(self.active)
        elif self.active is not None:
            self.active.last_timestamp = bar.timestamp
            self.active.closest_distance = min(
                self.active.closest_distance, self._distance(bar)
            )

        if self.active is not None and self._crossed(bar):
            self.active.confirmed_cross_timestamp = bar.timestamp
            self.active.confirmed_cross_close = bar.close
            if self.active.number == 3:
                return True
            self.failed_early_cross = True
            return False

        if self.active is not None and self._moves_away(bar):
            self.active.last_timestamp = bar.timestamp - timedelta(minutes=5)
            self.active = None
        return False


def aggregate_five_minute(rows: dict[str, dict]) -> list[FiveMinuteBar]:
    buckets: dict[datetime, list[tuple[datetime, dict]]] = defaultdict(list)
    for timestamp, row in rows.items():
        moment = _dt(timestamp)
        if moment.strftime("%H:%M") < "09:15" or moment.strftime("%H:%M") > "15:14":
            continue
        start = moment.replace(
            minute=(moment.minute // 5) * 5, second=0, microsecond=0
        )
        buckets[start].append((moment, row))
    bars = []
    for start, values in sorted(buckets.items()):
        values.sort(key=lambda item: item[0])
        expected = [start + timedelta(minutes=index) for index in range(5)]
        if [timestamp for timestamp, _ in values] != expected:
            continue
        bars.append(FiveMinuteBar(
            start=start,
            timestamp=values[-1][0],
            open=float(values[0][1]["open"]),
            high=max(float(row["high"]) for _, row in values),
            low=min(float(row["low"]) for _, row in values),
            close=float(values[-1][1]["close"]),
        ))
    return bars


def directional_points(direction: str, entry: float, current: float) -> float:
    return current - entry if direction == "BULLISH" else entry - current


def outcome(
    bars: list[FiveMinuteBar],
    *,
    confirmation: FiveMinuteBar,
    new_direction: str,
) -> dict:
    later = [bar for bar in bars if bar.timestamp > confirmation.timestamp]
    close_horizons = {}
    for minutes in (5, 15, 30, 60):
        required = confirmation.timestamp + timedelta(minutes=minutes)
        bar = next((value for value in later if value.timestamp == required), None)
        close_horizons[f"close_points_plus_{minutes}m"] = (
            directional_points(new_direction, confirmation.close, bar.close)
            if bar else None
        )
    if new_direction == "BULLISH":
        mfe = max((bar.high - confirmation.close for bar in later), default=None)
        mae = min((bar.low - confirmation.close for bar in later), default=None)
    else:
        mfe = max((confirmation.close - bar.low for bar in later), default=None)
        mae = min((confirmation.close - bar.high for bar in later), default=None)
    return {
        **close_horizons,
        "session_mfe_points": mfe,
        "session_mae_points": mae,
        "session_last_timestamp": later[-1].timestamp.isoformat() if later else "",
        "session_last_points": (
            directional_points(new_direction, confirmation.close, later[-1].close)
            if later else None
        ),
    }


def scan_origin(
    *,
    block: str,
    session_date: str,
    entry: dict,
    bars: list[FiveMinuteBar],
    zone_points: float,
) -> dict | None:
    entry_timestamp = _dt(entry["event_timestamp"])
    origin_direction = entry["direction"]
    midpoint = float(entry["midpoint"])
    eligible = [bar for bar in bars if bar.start > entry_timestamp]
    detector = DhanushDetector(midpoint, origin_direction, zone_points)
    confirmation = None
    for bar in eligible:
        if detector.observe(bar):
            confirmation = bar
            break
        if detector.failed_early_cross:
            break
    if confirmation is None:
        return None
    new_direction = "BULLISH" if origin_direction == "BEARISH" else "BEARISH"
    row = {
        "block": block,
        "session_date": session_date,
        "origin_family": entry["family"],
        "origin_direction": origin_direction,
        "new_direction": new_direction,
        "origin_entry_timestamp": entry_timestamp.isoformat(),
        "origin_entry_price": entry["underlying_price"],
        "reference_type": entry["reference_type"],
        "midpoint": midpoint,
        "zone_points": zone_points,
        "attempt_1_start": detector.attempts[0].start_timestamp.isoformat(),
        "attempt_1_end": detector.attempts[0].last_timestamp.isoformat(),
        "attempt_1_closest_distance": detector.attempts[0].closest_distance,
        "attempt_2_start": detector.attempts[1].start_timestamp.isoformat(),
        "attempt_2_end": detector.attempts[1].last_timestamp.isoformat(),
        "attempt_2_closest_distance": detector.attempts[1].closest_distance,
        "attempt_3_start": detector.attempts[2].start_timestamp.isoformat(),
        "confirmation_timestamp": confirmation.timestamp.isoformat(),
        "confirmation_close": confirmation.close,
    }
    row.update(outcome(
        bars,
        confirmation=confirmation,
        new_direction=new_direction,
    ))
    return row


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict]) -> dict:
    def metric(name: str) -> dict:
        values = [float(row[name]) for row in rows if row[name] is not None]
        return {
            "n": len(values),
            "sum": sum(values),
            "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "positive": sum(value > 0 for value in values),
            "negative": sum(value < 0 for value in values),
        }
    return {
        "matches": len(rows),
        "origin_families": dict(Counter(row["origin_family"] for row in rows)),
        "new_directions": dict(Counter(row["new_direction"] for row in rows)),
        "plus_5m": metric("close_points_plus_5m"),
        "plus_15m": metric("close_points_plus_15m"),
        "plus_30m": metric("close_points_plus_30m"),
        "plus_60m": metric("close_points_plus_60m"),
        "session_mfe": metric("session_mfe_points"),
        "session_mae": metric("session_mae_points"),
        "session_last": metric("session_last_points"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone-points", type=float, default=10.0)
    arguments = parser.parse_args()
    if arguments.zone_points <= 0:
        raise SystemExit("STOP: zone points must be positive")

    v55 = _import(V55, "v55_for_dhanush")
    v52 = _import(V52, "v52_for_dhanush")
    canon = _import(CANON, "canon_for_dhanush")
    v57 = _import(V57, "v57_for_dhanush")
    matches = []
    sessions = 0
    origins = 0

    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for session_date in sorted(set(underlying).intersection(futures)):
            sessions += 1
            audit, _, _ = v57.replay_session(
                session_date, underlying[session_date], futures[session_date]
            )
            entries = [
                row for row in audit
                if row.get("event_type") in {"B_ENTRY", "E_ENTRY"}
            ]
            bars = aggregate_five_minute(underlying[session_date])
            for entry in entries:
                origins += 1
                match = scan_origin(
                    block=block["name"],
                    session_date=session_date,
                    entry=entry,
                    bars=bars,
                    zone_points=arguments.zone_points,
                )
                if match:
                    matches.append(match)

    august_25 = [row for row in matches if row["session_date"] == "2026-08-25"]
    expected = next(
        (row for row in august_25
         if row["origin_family"] == "B"
         and row["origin_direction"] == "BEARISH"),
        None,
    )
    if expected is None:
        raise SystemExit("STOP: frozen August 25 DHANUSH exemplar was not reproduced")

    report = {
        "model": "MIDPOINT_DHANUSH_V1",
        "definition": {
            "timeframe": "COMPLETED_5_MINUTE",
            "zone_points": arguments.zone_points,
            "distinct_attempts": 3,
            "first_two": "REJECT_WITHOUT_COMPLETED_CLOSE_CROSS",
            "third": "COMPLETED_CLOSE_CROSSES_EXACT_MIDPOINT",
            "symmetric": True,
        },
        "sessions": sessions,
        "origin_be_entries": origins,
        "summary": summarize(matches),
        "august_25": august_25,
        "safety": {
            "research_only": True,
            "live_mutation": False,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "orders_sent": False,
        },
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUTDIR / "matches.csv", matches)
    (OUTDIR / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(f"Sessions: {sessions} B/E origins: {origins} DHANUSH: {len(matches)}")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print("AUGUST 25")
    for row in august_25:
        print(
            row["origin_family"], row["origin_entry_timestamp"],
            row["attempt_1_start"], row["attempt_2_start"],
            row["attempt_3_start"], row["confirmation_timestamp"],
            row["new_direction"], row["session_mfe_points"],
        )
    print(f"Output: {OUTDIR / 'report.json'}")
    print("Research only: live strategy, workers, audits and orders untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
