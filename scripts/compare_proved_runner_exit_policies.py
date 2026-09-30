#!/usr/bin/env python3
"""Compare exit policies for one proved B/E replay trade.

The three-tier result is labelled counterfactual when the canonical classifier
was RUNNER_STRENGTHENING. This script never changes live configuration, audits,
orders, option tapes, or quantities.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.backtest_normal_b_proved import backtest_normal_b_proved


DEFAULT_REPLAY_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-ui-replay-v1"
)
ENTRY_TYPES = {"B_ENTRY", "E_ENTRY"}
LIVE_AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")
INDEX_INSTRUMENT = "NSE_INDEX|Nifty 50"
MARKET_START = time(9, 15)
MARKET_MINUTES = 360


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_session_sources(
    session_date: str, replay_root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Use replay when present; otherwise fetch index minutes read-only."""

    session_root = replay_root / session_date
    replay_audit = session_root / "audit.jsonl"
    replay_minutes = session_root / "minutes.jsonl"
    if replay_audit.is_file() and replay_minutes.is_file():
        return (
            _load_jsonl(replay_audit),
            _load_jsonl(replay_minutes),
            "HISTORICAL_REPLAY",
        )

    if not LIVE_AUDIT.is_file():
        raise FileNotFoundError(
            f"Neither replay audit nor live audit is available for {session_date}"
        )
    audit = [
        row
        for row in _load_jsonl(LIVE_AUDIT)
        if row.get("session_date") == session_date
    ]
    if not audit:
        raise ValueError(f"Live audit has no events for {session_date}")

    # Lazy imports keep ordinary replay research independent of broker modules.
    from dotenv import load_dotenv

    from market_lab.domain import IST
    from market_lab.upstox_live_shadow_sources_v1 import (
        UpstoxLiveShadowSourcesV1,
    )

    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise ValueError("UPSTOX_ACCESS_TOKEN is required for live-audit fallback")
    day = date.fromisoformat(session_date)
    expected = [
        datetime.combine(day, MARKET_START, IST) + timedelta(minutes=index)
        for index in range(MARKET_MINUTES)
    ]
    source = UpstoxLiveShadowSourcesV1(token)
    try:
        candles = source.historical_candles(INDEX_INSTRUMENT, day)
    finally:
        source.close()
    indexed = {}
    for candle in candles:
        timestamp = candle.timestamp.astimezone(IST)
        if timestamp in expected:
            if timestamp in indexed:
                raise ValueError(f"Duplicate historical index minute: {timestamp}")
            indexed[timestamp] = candle
    missing = [timestamp for timestamp in expected if timestamp not in indexed]
    if missing:
        sample = [timestamp.strftime("%H:%M") for timestamp in missing[:10]]
        raise ValueError(
            f"Exact 360 historical index minutes required; missing={sample}"
        )
    minutes = [
        {
            "session_date": session_date,
            "timestamp": timestamp.isoformat(),
            "underlying_open": float(indexed[timestamp].open),
            "underlying_high": float(indexed[timestamp].high),
            "underlying_low": float(indexed[timestamp].low),
            "underlying_close": float(indexed[timestamp].close),
            "data_status": "UNDERLYING_ONLY",
        }
        for timestamp in expected
    ]
    return audit, minutes, "LIVE_AUDIT_PLUS_UPSTOX_HISTORICAL_INDEX_1M"


def _directional_points(direction: str, entry: float, price: float) -> float:
    sign = 1.0 if direction == "BULLISH" else -1.0
    return sign * (price - entry)


def _find_trade_events(
    audit: list[dict[str, Any]], entry_timestamp: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries = [row for row in audit if row.get("event_type") in ENTRY_TYPES]
    entry = next(
        (row for row in entries if row.get("event_timestamp") == entry_timestamp),
        None,
    )
    if entry is None:
        available = [row.get("event_timestamp") for row in entries]
        raise ValueError(
            f"Entry {entry_timestamp} unavailable; available entries: {available}"
        )
    later_entries = sorted(
        str(row["event_timestamp"])
        for row in entries
        if str(row.get("event_timestamp")) > entry_timestamp
    )
    end = later_entries[0] if later_entries else "9999"
    events = [
        row
        for row in audit
        if entry_timestamp <= str(row.get("event_timestamp", "")) < end
    ]
    return entry, events


def _minute_frame(
    rows: list[dict[str, Any]], *, entry_timestamp: str, entry_price: float,
    direction: str
) -> pd.DataFrame:
    frame = pd.DataFrame(rows).rename(
        columns={
            "timestamp": "Timestamp",
            "underlying_open": "Open",
            "underlying_high": "High",
            "underlying_low": "Low",
            "underlying_close": "Close",
        }
    )
    required = {"Timestamp", "Open", "High", "Low", "Close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Replay minutes missing columns: {missing}")
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="raise")
    frame = frame.loc[
        frame["Timestamp"] > pd.Timestamp(entry_timestamp),
        ["Timestamp", "Open", "High", "Low", "Close"],
    ].copy()
    sign = 1.0 if direction == "BULLISH" else -1.0
    favourable = (
        frame["High"].to_numpy(dtype=float)
        if direction == "BULLISH"
        else frame["Low"].to_numpy(dtype=float)
    )
    excursion = sign * (favourable - entry_price)
    frame["Intrabar_MFE"] = np.maximum.accumulate(
        np.maximum(excursion, 0.0)
    )
    return frame.reset_index(drop=True)


def _event_projection(
    event: dict[str, Any] | None, *, entry_price: float, direction: str,
    trigger: str
) -> dict[str, Any] | None:
    if event is None or event.get("underlying_price") is None:
        return None
    price = float(event["underlying_price"])
    return {
        "timestamp": event["event_timestamp"],
        "trigger": trigger,
        "price": price,
        "directional_points": _directional_points(
            direction, entry_price, price
        ),
        "valuation_basis": "OBSERVED_CANDLE_CLOSE",
    }


def compare_session_trade(
    *, session_date: str, entry_timestamp: str,
    replay_root: Path = DEFAULT_REPLAY_ROOT
) -> dict[str, Any]:
    audit, minute_rows, data_source = _load_session_sources(
        session_date, replay_root
    )
    entry, events = _find_trade_events(audit, entry_timestamp)
    direction = str(entry["direction"])
    entry_price = float(entry["underlying_price"])
    midpoint = float(entry["midpoint"])

    classifier = next(
        (row for row in events if row.get("event_type") == "RUNNER_CLASSIFICATION"),
        None,
    )
    if classifier is None:
        raise ValueError("Trade has no exact RUNNER_CLASSIFICATION event")
    classifier_result = str(classifier.get("result"))
    if classifier_result not in {"NORMAL_B", "RUNNER_STRENGTHENING"}:
        raise ValueError(f"Unsupported classifier result: {classifier_result}")

    minutes = _minute_frame(
        minute_rows,
        entry_timestamp=entry_timestamp,
        entry_price=entry_price,
        direction=direction,
    )
    three_tier, _ = backtest_normal_b_proved(
        minutes,
        entry_timestamp=entry_timestamp,
        activation_timestamp=classifier["event_timestamp"],
        entry_price=entry_price,
        midpoint_price=midpoint,
        direction=direction,
    )
    degraded_event = next(
        (row for row in events if row.get("event_type") == "DEGRADED_STARTED"),
        None,
    )
    terminal_event = next(
        (
            row
            for row in events
            if row.get("event_type")
            in {"STRUCTURAL_TERMINAL", "CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT"}
        ),
        None,
    )
    baseline = _event_projection(
        terminal_event,
        entry_price=entry_price,
        direction=direction,
        trigger=(
            str(terminal_event.get("event_type"))
            if terminal_event is not None
            else "UNRESOLVED"
        ),
    )
    degraded = _event_projection(
        degraded_event,
        entry_price=entry_price,
        direction=direction,
        trigger="DEGRADED_STARTED_CLOSE",
    )
    three_tier_result = three_tier.to_dict()
    points = {
        "STRUCTURAL_BASELINE": (
            None if baseline is None else baseline["directional_points"]
        ),
        "DEGRADED_EXIT": (
            None if degraded is None else degraded["directional_points"]
        ),
        "THREE_TIER": three_tier.total_captured_points,
    }
    available = {key: value for key, value in points.items() if value is not None}
    winner = max(available, key=available.get) if available else None
    return {
        "model": "MIDPOINT_PROVED_RUNNER_EXIT_POLICY_COMPARISON_V1",
        "session_date": session_date,
        "family": entry.get("family"),
        "direction": direction,
        "entry_timestamp": entry_timestamp,
        "entry_price": entry_price,
        "midpoint": midpoint,
        "classifier_timestamp": classifier["event_timestamp"],
        "classifier_result": classifier_result,
        "data_source": data_source,
        "three_tier_policy_status": (
            "CANONICAL_NORMAL_B_PROVED"
            if classifier_result == "NORMAL_B"
            else "COUNTERFACTUAL_ON_RUNNER_STRENGTHENING"
        ),
        "structural_baseline": baseline,
        "degraded_exit": degraded,
        "three_tier": three_tier_result,
        "comparison_points": points,
        "best_observed_policy": winner,
        "safety": {
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
        "interpretation": (
            "Underlying-only counterfactual comparison. The degraded value is "
            "the completed DEGRADED_STARTED candle close; option valuation, "
            "bid/ask, slippage, charges and quantity are excluded."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--entry-timestamp", required=True)
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY_ROOT)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = compare_session_trade(
        session_date=arguments.session_date,
        entry_timestamp=arguments.entry_timestamp,
        replay_root=arguments.replay_root,
    )
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
