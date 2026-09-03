from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.paper_strategy_authority import PaperStrategyAuthority
from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    RedBarV2UISnapshot,
    read_red_bar_v2_ui_snapshot,
)

IST = ZoneInfo("Asia/Kolkata")

# `recorded_at` is stamped when the snapshot artifact is written, which is
# necessarily *after* the caller captured `now` for the cycle: the paper
# monitor takes `cycle_started` at the top of the loop and only reaches the
# freshness check once the day replay and its persistence have finished. A
# `recorded_at` reading slightly ahead of `now` is therefore the normal,
# healthy case, and it is tolerated up to this bound. Beyond it the artifact
# clock is not trustworthy and freshness falls back to the admission stamp.
MAXIMUM_RECORDED_FORWARD_SKEW_SECONDS = 120.0


@dataclass(frozen=True)
class RedBarV2PaperSignalPublishResult:
    status: str
    reason: str
    signal_id: str | None = None


def _signal_id(snapshot: RedBarV2UISnapshot) -> str:
    raw = "|".join(
        [
            "RED_BAR_V2",
            str(snapshot.direction or "NONE"),
            str(snapshot.admission_timestamp or "NONE"),
            str(snapshot.reference_timestamp or "NONE"),
            str(snapshot.admission_code or "NONE"),
        ]
    )
    return f"RBV2-{sha256(raw.encode('utf-8')).hexdigest()[:24].upper()}"


def _timestamp(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("Asia/Kolkata")
    else:
        parsed = parsed.tz_convert("Asia/Kolkata")
    return parsed


def validate_snapshot_for_paper(
    snapshot: RedBarV2UISnapshot | None,
    *,
    authority: PaperStrategyAuthority,
    now: datetime | pd.Timestamp | None = None,
    maximum_age_seconds: int = 120,
) -> RedBarV2PaperSignalPublishResult:
    valid, reason = authority.validate()
    if not valid:
        return RedBarV2PaperSignalPublishResult("BLOCKED", reason)
    if not authority.v2_paper_active:
        return RedBarV2PaperSignalPublishResult("DISABLED", "V2_PAPER_AUTHORITY_DISABLED")
    if snapshot is None:
        return RedBarV2PaperSignalPublishResult("WAITING", "V2_SNAPSHOT_UNAVAILABLE")
    if str(snapshot.alignment_status or "").upper() not in {"READY", "ALIGNED"}:
        return RedBarV2PaperSignalPublishResult("BLOCKED", "V2_SOURCE_ALIGNMENT_NOT_READY")
    if snapshot.admission_allowed is not True:
        return RedBarV2PaperSignalPublishResult(
            "WAITING",
            str(snapshot.admission_code or "V2_CANDIDATE_NOT_ADMITTED"),
        )
    if snapshot.direction not in {"BULLISH", "BEARISH"}:
        return RedBarV2PaperSignalPublishResult("WAITING", "V2_DIRECTION_UNAVAILABLE")
    evaluation = _timestamp(snapshot.admission_timestamp)
    if evaluation is None:
        return RedBarV2PaperSignalPublishResult("BLOCKED", "V2_ADMISSION_TIMESTAMP_INVALID")
    current = pd.Timestamp(now or datetime.now(IST))
    if current.tzinfo is None:
        current = current.tz_localize("Asia/Kolkata")
    else:
        current = current.tz_convert("Asia/Kolkata")
    recorded = _timestamp(snapshot.recorded_at)
    # Freshness is a property of the artifact, so prefer its write time.
    # The previous `evaluation <= recorded <= current` window could never
    # hold (see MAXIMUM_RECORDED_FORWARD_SKEW_SECONDS), which silently
    # pinned freshness to `admission_timestamp` -- a candle stamp that does
    # not advance while a direction persists -- and blocked the bridge with
    # V2_SNAPSHOT_STALE for the rest of the session about two minutes after
    # the day's first admission.
    recorded_is_usable = (
        recorded is not None
        and evaluation <= recorded
        and (recorded - current).total_seconds()
        <= MAXIMUM_RECORDED_FORWARD_SKEW_SECONDS
    )
    if recorded is not None and recorded_is_usable:
        freshness_ref = recorded
        age_seconds = max(0.0, float((current - recorded).total_seconds()))
    else:
        freshness_ref = evaluation
        age_seconds = float((current - evaluation).total_seconds())
    if freshness_ref.date() != current.date():
        return RedBarV2PaperSignalPublishResult("BLOCKED", "V2_SNAPSHOT_NOT_CURRENT_SESSION")
    if age_seconds < 0 or age_seconds > maximum_age_seconds:
        return RedBarV2PaperSignalPublishResult("BLOCKED", "V2_SNAPSHOT_STALE")
    return RedBarV2PaperSignalPublishResult("READY", "V2_PAPER_SIGNAL_READY", _signal_id(snapshot))


def publish_v2_snapshot_to_paper_signals(
    *,
    database_path: str | Path,
    artifacts_root: str | Path,
    instrument_key: str,
    authority: PaperStrategyAuthority,
    now: datetime | pd.Timestamp | None = None,
    maximum_age_seconds: int = 120,
) -> RedBarV2PaperSignalPublishResult:
    snapshot = read_red_bar_v2_ui_snapshot(artifacts_root)
    result = validate_snapshot_for_paper(
        snapshot,
        authority=authority,
        now=now,
        maximum_age_seconds=maximum_age_seconds,
    )
    if result.status != "READY" or snapshot is None or result.signal_id is None:
        return result

    evaluation = _timestamp(snapshot.admission_timestamp)
    reference = _timestamp(snapshot.reference_timestamp)
    assert evaluation is not None
    trading_date = evaluation.date().isoformat()
    midpoint = float(snapshot.reference_midpoint or snapshot.index_close or 0.0)
    underlying_entry = (
        float(snapshot.index_close)
        if snapshot.index_close is not None
        else None
    )
    created_at = datetime.now(IST).isoformat()

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        columns = [
            "signal_id", "run_id", "instrument_key", "trading_date",
            "level_type", "level_value", "direction", "state",
            "cross_timestamp", "confirmation_timestamp", "underlying_entry",
        ]
        values: list[object] = [
            result.signal_id,
            snapshot.correlation_id or "RBV2-PAPER-RUNTIME",
            instrument_key,
            trading_date,
            "RED_BAR_V2",
            midpoint,
            snapshot.direction,
            "ACTIVE",
            (reference or evaluation).isoformat(),
            evaluation.isoformat(),
            underlying_entry,
        ]
        available = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(signal_attempts)")
        }
        if {"confirmation_high", "confirmation_low"}.issubset(available):
            columns.extend(("confirmation_high", "confirmation_low"))
            values.extend((snapshot.reference_high, snapshot.reference_low))
        # The level this admission was judged against, carried so the exit can ask
        # about *that* level rather than whichever one governs the session by the
        # time the position is being monitored. `level_value` above is always the
        # red bar's midpoint and must stay so -- `execution_policy` resolves a V2
        # row by `level_type` and the panels read `level_value` as the session's
        # reference -- so the entry's own level needs its own columns.
        entry_level = {
            "entry_type": snapshot.admission_entry_type,
            "governing_reference": snapshot.admission_reference,
            "governing_midpoint": (
                float(snapshot.admission_midpoint)
                if snapshot.admission_midpoint is not None
                else None
            ),
        }
        for column, value in entry_level.items():
            if column in available:
                columns.append(column)
                values.append(value)
        # The entry's risk plan, carried for the same reason as the entry level:
        # it was decided at the qualifying minute and cannot be recomputed later
        # without reading price that printed after the decision. The order path
        # reads ``risk_plan_tradable`` as gate 5; the rest is the arithmetic
        # behind it, so a refusal can be audited rather than trusted.
        risk_plan = {
            "risk_plan_tradable": (
                None
                if snapshot.risk_plan_tradable is None
                else int(bool(snapshot.risk_plan_tradable))
            ),
            "risk_plan_code": snapshot.risk_plan_code,
            "risk_plan_detail": snapshot.risk_plan_detail,
            "risk_stop_price": (
                float(snapshot.risk_stop_price)
                if snapshot.risk_stop_price is not None
                else None
            ),
            "risk_points": (
                float(snapshot.risk_points)
                if snapshot.risk_points is not None
                else None
            ),
            "risk_stop_trigger": snapshot.risk_stop_trigger,
        }
        for column, value in risk_plan.items():
            if column in available:
                columns.append(column)
                values.append(value)
        columns.extend(("confirmation_delay_minutes", "created_at"))
        values.extend((0, created_at))
        placeholders = ",".join("?" for _ in columns)
        update_cols = [c for c in columns if c not in ("signal_id", "instrument_key", "trading_date")]
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
        conn.execute(
            f"INSERT INTO signal_attempts({','.join(columns)}) "
            f"VALUES({placeholders}) "
            f"ON CONFLICT(signal_id) DO UPDATE SET {update_clause}",
            tuple(values),
        )
        conn.commit()
    return RedBarV2PaperSignalPublishResult(
        "PUBLISHED",
        str(snapshot.admission_code or "V2_ADMITTED"),
        result.signal_id,
    )
