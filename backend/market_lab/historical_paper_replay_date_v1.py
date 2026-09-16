from __future__ import annotations

import csv
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .domain import IST
from .historical_positioning_adapter_v1 import (
    PositioningRow,
    PositioningSession,
    choose_positioning_session,
    discover_positioning_sessions,
    timestamp_groups,
)
from .oi_vwap_causal_runtime_v1 import _directional_p1, _p2_persists, _vwap_aligned
from .oi_vwap_live_feature_engine_v1 import OICheckpointFeature
from .oi_vwap_live_futures_v1 import FuturesCandle, completed_futures_vwap


DEFAULT_FUTURES_CSV = Path(
    "data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv"
)


class HistoricalReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayEvent:
    session_date: str
    timestamp: str
    event_type: str
    status: str
    reason_code: str | None = None
    direction: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class ReplayResult:
    session_date: str
    positioning_source: str
    futures_source: str
    option_expiry: str
    events: list[ReplayEvent] = field(default_factory=list)
    p1_count: int = 0
    wait_p2_count: int = 0
    p2_confirmed_count: int = 0
    p2_failed_count: int = 0
    vwap_reject_count: int = 0
    feature_block_count: int = 0


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def _norm5(ts: datetime) -> datetime:
    ts = ts.astimezone(IST)
    minute = ts.minute - (ts.minute % 5)
    return ts.replace(minute=minute, second=0, microsecond=0)


def _sum_oi(rows: Iterable[PositioningRow]) -> tuple[int, int]:
    ce = 0
    pe = 0
    count = 0
    for row in rows:
        if row.ce_open_interest is None or row.pe_open_interest is None:
            raise HistoricalReplayError("OI missing for required strike")
        ce += int(row.ce_open_interest)
        pe += int(row.pe_open_interest)
        count += 1
    if count == 0:
        raise HistoricalReplayError("No strikes selected")
    return ce, pe


def _rows_by_strike(rows: Iterable[PositioningRow]) -> dict[float, PositioningRow]:
    return {float(row.strike): row for row in rows}


def _select_exact_strikes(
    rows: Iterable[PositioningRow],
    strikes: Iterable[float],
) -> list[PositioningRow]:
    by = _rows_by_strike(rows)
    selected = []
    missing = []
    for strike in strikes:
        key = float(strike)
        row = by.get(key)
        if row is None:
            missing.append(key)
        else:
            selected.append(row)
    if missing:
        raise HistoricalReplayError(f"Missing exact strikes: {missing}")
    return selected


def _current_pm2(rows: Iterable[PositioningRow]) -> list[PositioningRow]:
    selected = sorted(
        [row for row in rows if -2 <= row.strike_offset <= 2],
        key=lambda row: row.strike,
    )
    if len(selected) != 5:
        raise HistoricalReplayError(
            f"Expected 5 current ATM±2 strikes, found {len(selected)}"
        )
    return selected


def build_historical_oi_features(
    session: PositioningSession,
) -> list[OICheckpointFeature]:
    groups = timestamp_groups(session)
    if not groups:
        return []

    baseline_ts = None
    baseline_rows = None
    for ts, rows in groups.items():
        if ts.hour == 9 and ts.minute == 20:
            baseline_ts = ts
            baseline_rows = rows
            break
    if baseline_rows is None:
        raise HistoricalReplayError("09:20 session baseline unavailable")

    baseline_pm2 = _current_pm2(baseline_rows)
    fixed_strikes = [row.strike for row in baseline_pm2]
    baseline_ce, baseline_pe = _sum_oi(baseline_pm2)

    features: list[OICheckpointFeature] = []
    sorted_times = sorted(groups)

    for ts in sorted_times:
        # Strategy checkpoints begin after the 09:20 baseline.
        if ts <= baseline_ts:
            continue
        if ts.second != 0 or ts.microsecond != 0 or ts.minute % 5 != 0:
            continue

        previous_ts = ts - timedelta(minutes=5)
        previous_rows = groups.get(previous_ts)
        if previous_rows is None:
            continue

        current_rows = groups[ts]
        current_pm2 = _current_pm2(current_rows)
        current_strikes = [row.strike for row in current_pm2]

        previous_same = _select_exact_strikes(previous_rows, current_strikes)

        ce_now, pe_now = _sum_oi(current_pm2)
        ce_prev, pe_prev = _sum_oi(previous_same)
        ce_delta = ce_now - ce_prev
        pe_delta = pe_now - pe_prev
        imbalance = pe_delta - ce_delta

        pcr_now = pe_now / ce_now if ce_now else None
        pcr_prev = pe_prev / ce_prev if ce_prev else None
        pcr_change = (
            None if pcr_now is None or pcr_prev is None else pcr_now - pcr_prev
        )

        current_fixed = _select_exact_strikes(current_rows, fixed_strikes)
        ce_fixed, pe_fixed = _sum_oi(current_fixed)
        ce_session_delta = ce_fixed - baseline_ce
        pe_session_delta = pe_fixed - baseline_pe
        session_imbalance = pe_session_delta - ce_session_delta

        previous_fixed = _select_exact_strikes(previous_rows, fixed_strikes)
        ce_fixed_prev, pe_fixed_prev = _sum_oi(previous_fixed)
        previous_session_imbalance = (
            (pe_fixed_prev - baseline_pe) - (ce_fixed_prev - baseline_ce)
        )

        spot = float(current_rows[0].spot)
        atm = float(current_rows[0].moving_atm)

        features.append(
            OICheckpointFeature(
                observation_id=len(features) + 1,
                timestamp=ts.isoformat(),
                session_date=session.session_date,
                spot=spot,
                atm=atm,
                ce_oi=ce_now,
                pe_oi=pe_now,
                ce_delta_5m=ce_delta,
                pe_delta_5m=pe_delta,
                imbalance_5m=imbalance,
                pcr_current_5m=pcr_now,
                pcr_previous_5m=pcr_prev,
                pcr_change_5m=pcr_change,
                ce_session_delta=ce_session_delta,
                pe_session_delta=pe_session_delta,
                session_imbalance=session_imbalance,
                previous_session_imbalance=previous_session_imbalance,
            )
        )

    return features


def load_historical_futures_5m(
    session_date: str,
    *,
    csv_path: str | Path = DEFAULT_FUTURES_CSV,
) -> list[FuturesCandle]:
    path = Path(csv_path)
    if not path.exists():
        raise HistoricalReplayError(f"Futures CSV not found: {path}")

    target_rows = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"session_date", "timestamp", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise HistoricalReplayError(
                f"Futures CSV missing required columns: {sorted(required)}"
            )
        for row in reader:
            if row["session_date"] == session_date:
                target_rows.append(row)

    if not target_rows:
        raise HistoricalReplayError(
            f"No futures rows for {session_date} in {path}"
        )

    by_bucket: dict[datetime, list[dict]] = {}
    for row in target_rows:
        ts = _parse_ts(row["timestamp"])
        by_bucket.setdefault(_norm5(ts), []).append(row)

    candles: list[FuturesCandle] = []
    for bucket, rows in sorted(by_bucket.items()):
        rows = sorted(rows, key=lambda row: _parse_ts(row["timestamp"]))

        # Require all five 1-minute constituent rows for causal parity.
        expected = {bucket + timedelta(minutes=i) for i in range(5)}
        actual = {_parse_ts(row["timestamp"]).replace(second=0, microsecond=0) for row in rows}
        if expected != actual:
            continue

        candles.append(
            FuturesCandle(
                timestamp=bucket,
                open=float(rows[0]["open"]),
                high=max(float(row["high"]) for row in rows),
                low=min(float(row["low"]) for row in rows),
                close=float(rows[-1]["close"]),
                volume=sum(int(float(row["volume"])) for row in rows),
            )
        )

    if not candles:
        raise HistoricalReplayError(
            f"No complete 5-minute futures candles for {session_date}"
        )

    return candles


def replay_date(
    session_date: str,
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = DEFAULT_FUTURES_CSV,
) -> ReplayResult:
    positioning = choose_positioning_session(
        session_date,
        data_root=data_root,
    )
    futures = load_historical_futures_5m(
        session_date,
        csv_path=futures_csv,
    )
    features = build_historical_oi_features(positioning)

    result = ReplayResult(
        session_date=session_date,
        positioning_source=positioning.source_path,
        futures_source=str(futures_csv),
        option_expiry=positioning.expiry,
    )

    waiting: tuple[str, OICheckpointFeature] | None = None
    previous: OICheckpointFeature | None = None

    for current in features:
        if waiting is not None:
            direction, p1_feature = waiting
            p1_ts = _parse_ts(p1_feature.timestamp)
            current_ts = _parse_ts(current.timestamp)
            expected = _norm5(p1_ts) + timedelta(minutes=5)

            if _norm5(current_ts) > expected:
                result.p2_failed_count += 1
                result.events.append(
                    ReplayEvent(
                        session_date=session_date,
                        timestamp=current.timestamp,
                        event_type="P2_FAILED",
                        status="FAIL",
                        reason_code="P2_CHECKPOINT_MISSED",
                        direction=direction,
                    )
                )
                waiting = None
            elif _norm5(current_ts) == expected:
                if _p2_persists(direction, current):
                    result.p2_confirmed_count += 1
                    result.events.append(
                        ReplayEvent(
                            session_date=session_date,
                            timestamp=current.timestamp,
                            event_type="P2_CONFIRMED_RUNTIME",
                            status="PASS",
                            direction=direction,
                            data={"oi": asdict(current)},
                        )
                    )
                else:
                    result.p2_failed_count += 1
                    result.events.append(
                        ReplayEvent(
                            session_date=session_date,
                            timestamp=current.timestamp,
                            event_type="P2_FAILED",
                            status="FAIL",
                            reason_code="P2_PERSISTENCE_FAILED",
                            direction=direction,
                            data={"oi": asdict(current)},
                        )
                    )
                waiting = None

            previous = current
            continue

        direction, reason = _directional_p1(current, previous)
        if direction is None:
            result.events.append(
                ReplayEvent(
                    session_date=session_date,
                    timestamp=current.timestamp,
                    event_type="P1_NOT_DETECTED",
                    status="SKIPPED",
                    reason_code=reason,
                )
            )
            previous = current
            continue

        result.p1_count += 1
        result.events.append(
            ReplayEvent(
                session_date=session_date,
                timestamp=current.timestamp,
                event_type="P1_DETECTED",
                status="PASS",
                direction=direction,
                data={"oi": asdict(current)},
            )
        )

        available_at = _parse_ts(current.timestamp)
        try:
            vwap = completed_futures_vwap(futures, available_at=available_at)
        except Exception as exc:
            result.feature_block_count += 1
            result.events.append(
                ReplayEvent(
                    session_date=session_date,
                    timestamp=current.timestamp,
                    event_type="FUTURES_DATA_INVALID",
                    status="FAIL",
                    reason_code="FUTURES_VWAP_MISSING",
                    direction=direction,
                    data={"detail": str(exc)},
                )
            )
            previous = current
            continue

        if not _vwap_aligned(direction, vwap.side):
            result.vwap_reject_count += 1
            result.events.append(
                ReplayEvent(
                    session_date=session_date,
                    timestamp=current.timestamp,
                    event_type="VWAP_NOT_ALIGNED",
                    status="FAIL",
                    reason_code="VWAP_NOT_ALIGNED",
                    direction=direction,
                    data={"vwap": asdict(vwap)},
                )
            )
            previous = current
            continue

        result.wait_p2_count += 1
        waiting = (direction, current)
        result.events.append(
            ReplayEvent(
                session_date=session_date,
                timestamp=current.timestamp,
                event_type="WAIT_P2",
                status="WAITING",
                direction=direction,
                data={"vwap": asdict(vwap)},
            )
        )
        previous = current

    return result


def discover_available_dates(
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = DEFAULT_FUTURES_CSV,
) -> list[str]:
    positioning_dates = set()
    for path in discover_positioning_sessions(data_root=data_root):
        try:
            # Lightweight content read for discovery.
            import json
            payload = json.loads(path.read_text())
            if payload.get("status") == "AVAILABLE" and payload.get("session_date"):
                positioning_dates.add(str(payload["session_date"]))
        except Exception:
            continue

    futures_dates = set()
    with Path(futures_csv).open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("session_date"):
                futures_dates.add(row["session_date"])

    return sorted(positioning_dates & futures_dates)


def summarize(results: list[ReplayResult]) -> dict:
    return {
        "sessions": len(results),
        "p1_count": sum(r.p1_count for r in results),
        "wait_p2_count": sum(r.wait_p2_count for r in results),
        "p2_confirmed_count": sum(r.p2_confirmed_count for r in results),
        "p2_failed_count": sum(r.p2_failed_count for r in results),
        "vwap_reject_count": sum(r.vwap_reject_count for r in results),
        "feature_block_count": sum(r.feature_block_count for r in results),
    }
