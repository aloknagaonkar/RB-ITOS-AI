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
            str(snapshot.last_evaluation_timestamp or "NONE"),
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
    if str(snapshot.alignment_status or "").upper() != "READY":
        return RedBarV2PaperSignalPublishResult("BLOCKED", "V2_SOURCE_ALIGNMENT_NOT_READY")
    if snapshot.admission_allowed is not True:
        return RedBarV2PaperSignalPublishResult(
            "WAITING",
            str(snapshot.admission_code or "V2_CANDIDATE_NOT_ADMITTED"),
        )
    if snapshot.direction not in {"BULLISH", "BEARISH"}:
        return RedBarV2PaperSignalPublishResult("WAITING", "V2_DIRECTION_UNAVAILABLE")
    evaluation = _timestamp(snapshot.last_evaluation_timestamp)
    if evaluation is None:
        return RedBarV2PaperSignalPublishResult("BLOCKED", "V2_EVALUATION_TIMESTAMP_INVALID")
    current = pd.Timestamp(now or datetime.now(IST))
    if current.tzinfo is None:
        current = current.tz_localize("Asia/Kolkata")
    else:
        current = current.tz_convert("Asia/Kolkata")
    age_seconds = float((current - evaluation).total_seconds())
    if evaluation.date() != current.date():
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

    evaluation = _timestamp(snapshot.last_evaluation_timestamp)
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
            "RBV2-PAPER-RUNTIME",
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
        columns.extend(("confirmation_delay_minutes", "created_at"))
        values.extend((0, created_at))
        placeholders = ",".join("?" for _ in columns)
        conn.execute(
            f"INSERT OR IGNORE INTO signal_attempts({','.join(columns)}) "
            f"VALUES({placeholders})",
            tuple(values),
        )
        conn.commit()
    return RedBarV2PaperSignalPublishResult(
        "PUBLISHED",
        str(snapshot.admission_code or "V2_ADMITTED"),
        result.signal_id,
    )
