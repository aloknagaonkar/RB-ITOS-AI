from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from red_bar_lab.execution.rsi_extreme_reversal import (
    RsiExtremeReversalEngine,
    _rsi,
)


def _latest(rows: Iterable[Mapping[str, object]], fields: tuple[str, ...]):
    values = [dict(row) for row in rows]
    if not values:
        return {}
    return max(
        values,
        key=lambda row: next(
            (str(row.get(field) or "") for field in fields if row.get(field)),
            "",
        ),
    )


def _option_alignment(direction: object, option_bias: object) -> str:
    direction = str(direction or "").upper()
    bias = str(option_bias or "").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        return "NOT APPLICABLE"
    if bias in {"UNAVAILABLE", "NEUTRAL", ""}:
        return "NEUTRAL"
    if direction in bias:
        return "SUPPORTING"
    if (direction == "BULLISH" and "BEARISH" in bias) or (
        direction == "BEARISH" and "BULLISH" in bias
    ):
        return "CONFLICTING"
    return "MIXED"


def build_red_bar_setup_state(
    database,
    instrument_key: str,
    trading_date: str,
    *,
    reference: Mapping[str, object] | None,
    option_bias: object,
) -> dict[str, object]:
    attempts = list(database.read_signal_attempts(instrument_key, trading_date) or [])
    latest = _latest(attempts, ("confirmation_timestamp", "cross_timestamp"))
    reference = dict(reference or {})

    confirmed = bool(latest.get("confirmation_timestamp") and latest.get("direction"))
    crossed = bool(latest.get("cross_timestamp"))
    if confirmed:
        status = "CONFIRMED"
        waiting = "Contract selection and downstream execution gates"
        blocker = "None at strategy-detection layer"
    elif crossed:
        status = "CROSS DETECTED"
        waiting = "Confirmation candle acceptance"
        blocker = "No confirmed direction is persisted yet"
    elif reference:
        status = "REFERENCE READY"
        waiting = "Completed price cross of the Red Bar midpoint"
        blocker = "Midpoint cross has not been detected"
    else:
        status = "WAITING FOR REFERENCE"
        waiting = "NEXT_RED_CANDLE reference creation"
        blocker = "No persisted Red Bar reference"

    direction = latest.get("direction") if confirmed else "WAIT"
    midpoint = reference.get("midpoint") or reference.get("level_value")
    rows = [
        {
            "condition": "NEXT_RED_CANDLE reference",
            "status": "PASS" if reference else "WAIT",
            "observed": reference.get("source_timestamp") or "Not persisted",
        },
        {
            "condition": "Midpoint available",
            "status": "PASS" if midpoint not in (None, "") else "WAIT",
            "observed": midpoint if midpoint not in (None, "") else "Unavailable",
        },
        {
            "condition": "Midpoint cross",
            "status": "PASS" if crossed else "WAIT",
            "observed": latest.get("cross_timestamp") or "Not detected",
        },
        {
            "condition": "Confirmation candle",
            "status": "PASS" if confirmed else "WAIT",
            "observed": latest.get("confirmation_timestamp") or "Not confirmed",
        },
    ]
    return {
        "status": status,
        "direction": direction,
        "setup_id": latest.get("signal_id") or "Not created",
        "waiting_for": waiting,
        "blocker": blocker,
        "option_alignment": _option_alignment(direction, option_bias),
        "rows": rows,
    }


def _normalized_rsi_frame(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    if candles.empty or not required.issubset(candles.columns):
        return pd.DataFrame()
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
    frame["rsi"] = _rsi(frame["close"], 7)
    return frame


def build_rsi_setup_state(
    candles: pd.DataFrame,
    instrument_key: str,
    *,
    option_bias: object,
) -> dict[str, object]:
    frame = _normalized_rsi_frame(candles)
    if frame.empty or frame["rsi"].dropna().empty:
        return {
            "status": "NOT READY",
            "direction": "WAIT",
            "setup_id": "Not created",
            "waiting_for": "Sufficient completed candles for Wilder RSI(7)",
            "blocker": "RSI series is unavailable",
            "option_alignment": "NOT APPLICABLE",
            "rows": [],
        }

    signals = [
        item.as_record()
        for item in RsiExtremeReversalEngine().detect(
            candles,
            instrument_key=instrument_key,
        )
    ]
    latest_signal = _latest(signals, ("confirmation_timestamp",))
    last = frame.iloc[-1]
    previous = frame.iloc[-2] if len(frame) >= 2 else last
    current_rsi = float(last["rsi"])
    previous_rsi = float(previous["rsi"]) if pd.notna(previous["rsi"]) else current_rsi
    bullish = float(last["close"]) > float(last["open"])
    bearish = float(last["close"]) < float(last["open"])
    bullish_reclaim = float(last["close"]) > float(previous["high"])
    bearish_reclaim = float(last["close"]) < float(previous["low"])
    no_lower_low = float(last["low"]) >= float(previous["low"])
    no_higher_high = float(last["high"]) <= float(previous["high"])

    recent = frame.tail(6)
    ce_armed = bool((recent["rsi"] <= 20.0).any())
    pe_armed = bool((recent["rsi"] >= 80.0).any())
    ce_cross = previous_rsi <= 20.0 < current_rsi
    pe_cross = previous_rsi >= 80.0 > current_rsi

    if latest_signal:
        status = "CONFIRMED"
        direction = latest_signal.get("direction") or "WAIT"
        setup_id = latest_signal.get("signal_id") or "Not created"
        waiting = "Two-contract selection and downstream execution gates"
        blocker = "None at strategy-detection layer"
    elif ce_armed or pe_armed:
        status = "ARMED"
        direction = "CE WATCH" if ce_armed and not pe_armed else "PE WATCH" if pe_armed and not ce_armed else "WAIT"
        setup_id = "Not created"
        waiting = "Cross-back, candle direction, structure reclaim and adverse-extreme check"
        blocker = "All reversal confirmation conditions have not passed together"
    else:
        status = "WAITING FOR EXTREME"
        direction = "WAIT"
        setup_id = "Not created"
        waiting = "RSI <= 20 for CE watch or RSI >= 80 for PE watch"
        blocker = "No active RSI extreme in the five-candle window"

    confirmed_direction = str(latest_signal.get("direction") or "")
    ce_path = confirmed_direction == "BULLISH" or ce_armed
    rows = [
        {
            "condition": "Extreme armed",
            "status": "PASS" if ce_armed or pe_armed or latest_signal else "WAIT",
            "observed": f"RSI(7)={current_rsi:.2f}",
        },
        {
            "condition": "Cross-back",
            "status": "PASS" if ce_cross or pe_cross or latest_signal else "WAIT",
            "observed": f"previous={previous_rsi:.2f}; current={current_rsi:.2f}",
        },
        {
            "condition": "Candle direction",
            "status": "PASS" if (bullish if ce_path else bearish) or latest_signal else "WAIT",
            "observed": "Bullish" if bullish else "Bearish" if bearish else "Doji",
        },
        {
            "condition": "Structure reclaim",
            "status": "PASS" if (bullish_reclaim if ce_path else bearish_reclaim) or latest_signal else "WAIT",
            "observed": "Previous high reclaimed" if bullish_reclaim else "Previous low broken" if bearish_reclaim else "Not reclaimed",
        },
        {
            "condition": "No fresh adverse extreme",
            "status": "PASS" if (no_lower_low if ce_path else no_higher_high) or latest_signal else "WAIT",
            "observed": "Passed" if (no_lower_low if ce_path else no_higher_high) else "Adverse extreme present",
        },
    ]
    signal_direction = latest_signal.get("direction") if latest_signal else ""
    return {
        "status": status,
        "direction": direction,
        "setup_id": setup_id,
        "waiting_for": waiting,
        "blocker": blocker,
        "option_alignment": _option_alignment(signal_direction, option_bias),
        "rows": rows,
    }


def _safe_instrument(instrument_key: str) -> str:
    return instrument_key.replace("|", "_").replace(" ", "_").replace("/", "_").replace("\\", "_")


def _read_jsonl_for_date(path: Path, trading_date: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        timestamps = (
            row.get("detected_at"),
            row.get("timestamp"),
            row.get("updated_at"),
            row.get("started_at"),
        )
        if any(str(value or "")[:10] == trading_date for value in timestamps):
            rows.append(row)
    return rows


def build_dri_setup_state(
    runs_root: str | Path,
    instrument_key: str,
    trading_date: str,
    *,
    option_bias: object,
) -> dict[str, object]:
    root = Path(runs_root)
    name = f"{_safe_instrument(instrument_key)}.jsonl"
    regimes = _read_jsonl_for_date(root / "stateful_regime_v43" / name, trading_date)
    transitions = _read_jsonl_for_date(root / "transition_sequence_v43" / name, trading_date)
    signals = _read_jsonl_for_date(root / "fresh_setup_signals_v43" / name, trading_date)
    bundles = _read_jsonl_for_date(root / "fresh_setup_bundles_v43" / name, trading_date)
    regime = _latest(regimes, ("timestamp",))
    transition = _latest(transitions, ("updated_at", "started_at"))
    signal = _latest(signals, ("detected_at",))
    bundle = _latest(bundles, ("detected_at",))

    if bundle:
        status = "SETUP BUNDLED"
        direction = bundle.get("direction") or "WAIT"
        setup_id = bundle.get("bundle_id") or "Not created"
        waiting = "Contract selection and downstream execution gates"
        blocker = "None at DRI setup-detection layer"
    elif signal:
        status = "SETUP DETECTED"
        direction = signal.get("direction") or "WAIT"
        setup_id = signal.get("signal_id") or "Not created"
        waiting = "Fresh setup bundling and conflict resolution"
        blocker = "No setup bundle is stored for the detected signal"
    elif transition:
        status = "TRANSITION TRACKING"
        direction = transition.get("direction") or "WAIT"
        setup_id = transition.get("transition_id") or "Not created"
        waiting = "Fresh directional setup confirmation"
        blocker = "Transition has not produced a fresh setup signal"
    elif regime:
        status = "REGIME CLASSIFIED"
        direction = regime.get("direction") or regime.get("regime") or "WAIT"
        setup_id = regime.get("regime_snapshot_id") or "Not created"
        waiting = "Directional transition sequence"
        blocker = "No actionable transition is stored"
    else:
        status = "WAITING FOR REGIME"
        direction = "WAIT"
        setup_id = "Not created"
        waiting = "Stateful multi-timeframe regime snapshot"
        blocker = "No DRI regime artifact exists for the selected date"

    rows = [
        {"condition": "Regime snapshot", "status": "PASS" if regime else "WAIT", "observed": regime.get("regime_snapshot_id") or regime.get("timestamp") or "Not stored"},
        {"condition": "Transition sequence", "status": "PASS" if transition else "WAIT", "observed": transition.get("transition_id") or "Not stored"},
        {"condition": "Fresh setup signal", "status": "PASS" if signal else "WAIT", "observed": signal.get("setup_type") or "Not detected"},
        {"condition": "Setup bundle", "status": "PASS" if bundle else "WAIT", "observed": bundle.get("bundle_id") or "Not created"},
        {"condition": "Red Bar alignment", "status": str(bundle.get("red_bar_alignment") or "OBSERVE"), "observed": bundle.get("red_bar_alignment") or "Not available"},
    ]
    return {
        "status": status,
        "direction": direction,
        "setup_id": setup_id,
        "waiting_for": waiting,
        "blocker": blocker,
        "option_alignment": _option_alignment(direction, option_bias),
        "rows": rows,
    }
