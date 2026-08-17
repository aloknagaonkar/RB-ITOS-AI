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
            "observed": str(midpoint) if midpoint not in (None, "") else "Unavailable",
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


def _empty_rsi_decision_trace() -> dict[str, object]:
    return {
        "evaluation_timestamp": "Unavailable",
        "path": "UNDECIDED",
        "previous_candle": {},
        "current_candle": {},
        "recent_extreme": {},
        "checks": [],
        "first_unmet_condition": "Sufficient completed candles are unavailable.",
        "final_outcome": "NOT READY",
        "next_step": "Wait for enough completed 1-minute candles.",
    }


def _format_number(value: object, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if pd.isna(number):
        return "Unavailable"
    return f"{number:,.{digits}f}"


def _candle_record(row: pd.Series) -> dict[str, object]:
    timestamp = row.get("timestamp")
    if pd.isna(timestamp):
        timestamp_text = "Unavailable"
    else:
        timestamp_text = pd.Timestamp(timestamp).isoformat()
    return {
        "timestamp": timestamp_text,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "rsi": float(row["rsi"]) if pd.notna(row.get("rsi")) else None,
    }


def _rsi_check(
    sequence: int,
    condition: str,
    required: str,
    observed: str,
    passed: bool,
    explanation: str,
) -> dict[str, object]:
    return {
        "sequence": int(sequence),
        "condition": str(condition),
        "required": str(required),
        "observed": str(observed),
        "status": "PASS" if passed else "WAIT",
        "explanation": str(explanation),
    }


def _evaluation_index(frame: pd.DataFrame, latest_signal: Mapping[str, object]) -> int:
    if not latest_signal:
        return len(frame) - 1
    raw_timestamp = latest_signal.get("confirmation_timestamp")
    if raw_timestamp in (None, ""):
        return len(frame) - 1
    try:
        signal_ts = pd.Timestamp(raw_timestamp)
        if signal_ts.tzinfo is None:
            signal_ts = signal_ts.tz_localize("UTC")
        else:
            signal_ts = signal_ts.tz_convert("UTC")
        matches = frame.index[frame["timestamp"] == signal_ts].tolist()
        if matches:
            return int(matches[-1])
    except (TypeError, ValueError):
        pass
    return len(frame) - 1


def build_rsi_setup_state(
    candles: pd.DataFrame,
    instrument_key: str,
    *,
    option_bias: object,
) -> dict[str, object]:
    frame = _normalized_rsi_frame(candles)
    if len(frame) < 2 or frame["rsi"].dropna().empty:
        return {
            "status": "NOT READY",
            "direction": "WAIT",
            "setup_id": "Not created",
            "waiting_for": "Sufficient completed candles for Wilder RSI(7)",
            "blocker": "RSI series is unavailable",
            "option_alignment": "NOT APPLICABLE",
            "rows": [],
            "decision_trace": _empty_rsi_decision_trace(),
        }

    signals = [
        item.as_record()
        for item in RsiExtremeReversalEngine().detect(
            candles,
            instrument_key=instrument_key,
        )
    ]
    latest_signal = _latest(signals, ("confirmation_timestamp",))
    evaluation_index = _evaluation_index(frame, latest_signal)
    if evaluation_index < 1 or pd.isna(frame.iloc[evaluation_index].get("rsi")):
        return {
            "status": "NOT READY",
            "direction": "WAIT",
            "setup_id": "Not created",
            "waiting_for": "Sufficient completed candles for Wilder RSI(7)",
            "blocker": "RSI series is unavailable",
            "option_alignment": "NOT APPLICABLE",
            "rows": [],
            "decision_trace": _empty_rsi_decision_trace(),
        }

    last = frame.iloc[evaluation_index]
    previous = frame.iloc[evaluation_index - 1]
    current_rsi = float(last["rsi"])
    previous_rsi = float(previous["rsi"]) if pd.notna(previous["rsi"]) else current_rsi
    bullish = float(last["close"]) > float(last["open"])
    bearish = float(last["close"]) < float(last["open"])
    bullish_reclaim = float(last["close"]) > float(previous["high"])
    bearish_reclaim = float(last["close"]) < float(previous["low"])
    no_lower_low = float(last["low"]) >= float(previous["low"])
    no_higher_high = float(last["high"]) <= float(previous["high"])

    recent_start = max(0, evaluation_index - 5)
    recent = frame.iloc[recent_start : evaluation_index + 1]
    valid_recent_rsi = recent["rsi"].dropna()
    lowest_rsi = float(valid_recent_rsi.min()) if not valid_recent_rsi.empty else None
    highest_rsi = float(valid_recent_rsi.max()) if not valid_recent_rsi.empty else None
    ce_armed = bool((valid_recent_rsi <= 20.0).any())
    pe_armed = bool((valid_recent_rsi >= 80.0).any())
    ce_cross = previous_rsi <= 20.0 < current_rsi
    pe_cross = previous_rsi >= 80.0 > current_rsi

    confirmed_direction = str(latest_signal.get("direction") or "").upper()
    if confirmed_direction == "BULLISH":
        path = "CE"
    elif confirmed_direction == "BEARISH":
        path = "PE"
    elif ce_cross or (ce_armed and not pe_armed):
        path = "CE"
    elif pe_cross or (pe_armed and not ce_armed):
        path = "PE"
    else:
        path = "UNDECIDED"

    if latest_signal:
        status = "CONFIRMED"
        direction = latest_signal.get("direction") or "WAIT"
        setup_id = latest_signal.get("signal_id") or "Not created"
        waiting = "Two-contract selection and downstream execution gates"
        blocker = "None at strategy-detection layer"
    elif ce_armed or pe_armed:
        status = "ARMED"
        direction = "CE WATCH" if path == "CE" else "PE WATCH" if path == "PE" else "WAIT"
        setup_id = "Not created"
        waiting = "Cross-back, candle direction, structure reclaim and adverse-extreme check"
        blocker = "All reversal confirmation conditions have not passed together"
    else:
        status = "WAITING FOR EXTREME"
        direction = "WAIT"
        setup_id = "Not created"
        waiting = "RSI <= 20 for CE watch or RSI >= 80 for PE watch"
        blocker = "No active RSI extreme in the six-candle window"

    if path == "CE":
        path_checks = (
            ce_armed,
            ce_cross,
            bullish,
            bullish_reclaim,
            no_lower_low,
        )
        structure_condition = "Structure reclaim"
        structure_required = "Current close > previous high"
        structure_observed = (
            f"Current close {_format_number(last['close'])} > previous high "
            f"{_format_number(previous['high'])}"
        )
        structure_wait = (
            f"Structure reclaim has not occurred: close={_format_number(last['close'])} "
            f"must exceed previous high={_format_number(previous['high'])}."
        )
        direction_required = "Current close > current open"
        direction_observed = (
            f"Current close {_format_number(last['close'])} > current open "
            f"{_format_number(last['open'])}"
        )
        adverse_required = "Current low >= previous low"
        adverse_observed = (
            f"Current low {_format_number(last['low'])} >= previous low "
            f"{_format_number(previous['low'])}"
        )
        extreme_explanation = (
            "An oversold extreme armed the CE reversal path."
            if ce_armed else "No RSI value at or below 20 is present in the recent window."
        )
        cross_explanation = (
            "RSI crossed back above 20."
            if ce_cross else
            f"Cross-back has not occurred: previous RSI={previous_rsi:.2f}, current RSI={current_rsi:.2f}."
        )
        direction_explanation = (
            "The current completed candle is bullish."
            if bullish else "Candle direction has not confirmed: current close must exceed current open."
        )
        structure_explanation = (
            "The current close reclaimed the previous candle high."
            if bullish_reclaim else structure_wait
        )
        adverse_explanation = (
            "No fresh lower low was created."
            if no_lower_low else
            f"A fresh adverse extreme is present: current low={_format_number(last['low'])} is below previous low={_format_number(previous['low'])}."
        )
    elif path == "PE":
        path_checks = (
            pe_armed,
            pe_cross,
            bearish,
            bearish_reclaim,
            no_higher_high,
        )
        structure_condition = "Structure break"
        structure_required = "Current close < previous low"
        structure_observed = (
            f"Current close {_format_number(last['close'])} < previous low "
            f"{_format_number(previous['low'])}"
        )
        structure_wait = (
            f"Structure break has not occurred: close={_format_number(last['close'])} "
            f"must fall below previous low={_format_number(previous['low'])}."
        )
        direction_required = "Current close < current open"
        direction_observed = (
            f"Current close {_format_number(last['close'])} < current open "
            f"{_format_number(last['open'])}"
        )
        adverse_required = "Current high <= previous high"
        adverse_observed = (
            f"Current high {_format_number(last['high'])} <= previous high "
            f"{_format_number(previous['high'])}"
        )
        extreme_explanation = (
            "An overbought extreme armed the PE reversal path."
            if pe_armed else "No RSI value at or above 80 is present in the recent window."
        )
        cross_explanation = (
            "RSI crossed back below 80."
            if pe_cross else
            f"Cross-back has not occurred: previous RSI={previous_rsi:.2f}, current RSI={current_rsi:.2f}."
        )
        direction_explanation = (
            "The current completed candle is bearish."
            if bearish else "Candle direction has not confirmed: current close must be below current open."
        )
        structure_explanation = (
            "The current close broke the previous candle low."
            if bearish_reclaim else structure_wait
        )
        adverse_explanation = (
            "No fresh higher high was created."
            if no_higher_high else
            f"A fresh adverse extreme is present: current high={_format_number(last['high'])} exceeds previous high={_format_number(previous['high'])}."
        )
    else:
        path_checks = (False, False, False, False, False)
        structure_condition = "Structure reclaim/break"
        structure_required = "CE: close > previous high; PE: close < previous low"
        structure_observed = "Path is undecided"
        undecided = "Waiting for an RSI extreme to determine the CE or PE path."
        extreme_explanation = undecided
        cross_explanation = undecided
        direction_explanation = undecided
        structure_explanation = undecided
        adverse_explanation = undecided
        direction_required = "CE: close > open; PE: close < open"
        direction_observed = "Path is undecided"
        adverse_required = "CE: low >= previous low; PE: high <= previous high"
        adverse_observed = "Path is undecided"

    checks = [
        _rsi_check(
            1,
            "RSI extreme",
            "Any recent RSI <= 20 or RSI >= 80",
            f"Lowest RSI={_format_number(lowest_rsi)}; highest RSI={_format_number(highest_rsi)}",
            path_checks[0],
            extreme_explanation,
        ),
        _rsi_check(
            2,
            "Cross-back",
            "CE: previous RSI <= 20 and current RSI > 20; PE: previous RSI >= 80 and current RSI < 80",
            f"Previous RSI={previous_rsi:.2f}; current RSI={current_rsi:.2f}",
            path_checks[1],
            cross_explanation,
        ),
        _rsi_check(
            3,
            "Candle direction",
            direction_required,
            direction_observed,
            path_checks[2],
            direction_explanation,
        ),
        _rsi_check(
            4,
            structure_condition,
            structure_required,
            structure_observed,
            path_checks[3],
            structure_explanation,
        ),
        _rsi_check(
            5,
            "No fresh adverse extreme",
            adverse_required,
            adverse_observed,
            path_checks[4],
            adverse_explanation,
        ),
    ]

    first_wait = next((check for check in checks if check["status"] == "WAIT"), None)
    if first_wait is None:
        first_unmet_condition = "None — all strategy-detection conditions passed."
    else:
        first_unmet_condition = str(first_wait["explanation"])

    all_checks_passed = all(check["status"] == "PASS" for check in checks)
    if latest_signal:
        final_outcome = "CONFIRMED"
        next_step = "Proceed to two-contract selection and downstream execution gates."
    elif all_checks_passed:
        final_outcome = "CONDITIONS PASSED"
        next_step = "Allow the existing RSI detector and normal pipeline to create and persist the signal."
    elif path == "UNDECIDED":
        final_outcome = "WAITING FOR EXTREME"
        next_step = "Wait for RSI <= 20 or RSI >= 80 to determine the CE or PE path."
    else:
        final_outcome = "WAITING"
        next_step = f"Wait for the first unmet condition to pass: {first_unmet_condition}"

    decision_trace = {
        "evaluation_timestamp": _candle_record(last)["timestamp"],
        "path": path,
        "previous_candle": _candle_record(previous),
        "current_candle": _candle_record(last),
        "recent_extreme": {
            "lowest_rsi": lowest_rsi,
            "highest_rsi": highest_rsi,
            "window_candles": int(len(recent)),
        },
        "checks": checks,
        "first_unmet_condition": first_unmet_condition,
        "final_outcome": final_outcome,
        "next_step": next_step,
    }

    rows = [
        {
            "condition": "Extreme armed",
            "status": "PASS" if path_checks[0] or latest_signal else "WAIT",
            "observed": f"Lowest RSI={_format_number(lowest_rsi)}; highest RSI={_format_number(highest_rsi)}",
        },
        {
            "condition": "Cross-back",
            "status": "PASS" if path_checks[1] or latest_signal else "WAIT",
            "observed": f"previous={previous_rsi:.2f}; current={current_rsi:.2f}",
        },
        {
            "condition": "Candle direction",
            "status": "PASS" if path_checks[2] or latest_signal else "WAIT",
            "observed": "Bullish" if bullish else "Bearish" if bearish else "Doji",
        },
        {
            "condition": structure_condition,
            "status": "PASS" if path_checks[3] or latest_signal else "WAIT",
            "observed": structure_observed,
        },
        {
            "condition": "No fresh adverse extreme",
            "status": "PASS" if path_checks[4] or latest_signal else "WAIT",
            "observed": adverse_observed,
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
        "decision_trace": decision_trace,
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
