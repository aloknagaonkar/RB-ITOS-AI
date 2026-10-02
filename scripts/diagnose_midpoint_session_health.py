#!/usr/bin/env python3
"""Causally reconstruct Midpoint health checkpoints for one audited session.

Read only. The script reuses the production observation-only health engine and
never mutates the live audit, runtime configuration, orders, or quantities.
Post-session broker candles may differ from the originally observed live
candles; every such entry-price difference is reported explicitly.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from market_lab.domain import IST
from market_lab.midpoint_strategy.entry_health_live_v1 import (
    MidpointEntryHealthLiveV1,
    entry_health_label,
    evaluate_t5_candidates,
)
from market_lab.midpoint_v2_nifty_futures_vwap_v1 import (
    UNDERLYING,
    _client,
    available_expiries,
    fetch_one_minute_candles,
    resolve_active_future,
)
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1


DEFAULT_AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")
DEFAULT_OUTPUT_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-session-health-diagnostic-v1"
)
ENTRY_TYPES = {
    "B_ENTRY",
    "C_ENTRY",
    "E_ENTRY",
    "PM_B_ENTRY",
    "PM_E_ENTRY",
    "B_REARM_ENTRY",
    "E_REARM_ENTRY",
}
START = time(9, 15)
END = time(15, 14)


def aware(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError(f"AWARE_TIMESTAMP_REQUIRED_{value}")
    return result.astimezone(IST).replace(second=0, microsecond=0)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def normalize_cached(rows: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        timestamp = aware(row["timestamp"])
        if timestamp.date() != day or not START <= timestamp.time() <= END:
            continue
        output.append(
            {
                "timestamp": timestamp,
                "underlying_open": float(row["underlying_open"]),
                "underlying_high": float(row["underlying_high"]),
                "underlying_low": float(row["underlying_low"]),
                "underlying_close": float(row["underlying_close"]),
                "futures_open": float(row.get("futures_open", row["futures_close"])),
                "futures_high": float(row.get("futures_high", row["futures_close"])),
                "futures_low": float(row.get("futures_low", row["futures_close"])),
                "futures_close": float(row["futures_close"]),
                "futures_volume": float(row["futures_volume"]),
                "futures_vwap": float(row["futures_vwap"]),
            }
        )
    return validate_market(output, day)


def validate_market(rows: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    rows = sorted(rows, key=lambda row: row["timestamp"])
    expected = [
        datetime.combine(day, START, IST) + timedelta(minutes=offset)
        for offset in range(360)
    ]
    observed = [row["timestamp"] for row in rows]
    if observed != expected:
        missing = [value.strftime("%H:%M") for value in expected if value not in set(observed)]
        raise ValueError(
            f"EXACT_360_MARKET_MINUTES_REQUIRED_{day}_missing={missing[:20]}_observed={len(rows)}"
        )
    if any(row["futures_volume"] <= 0 for row in rows):
        raise ValueError("POSITIVE_FUTURES_VOLUME_REQUIRED")
    return rows


def acquire_market(day: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise SystemExit("STOP: UPSTOX_ACCESS_TOKEN missing")
    source = UpstoxLiveShadowSourcesV1(token)
    try:
        index_rows = source.historical_candles(UNDERLYING, day)
        with _client() as client:
            contract = resolve_active_future(client, day, available_expiries(client))
            futures_rows = fetch_one_minute_candles(client, contract, day)
    finally:
        source.close()

    index = {
        aware(candle.timestamp): {
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
        }
        for candle in index_rows
        if aware(candle.timestamp).date() == day
        and START <= aware(candle.timestamp).time() <= END
    }
    futures = {
        aware(row["timestamp"]): row
        for row in futures_rows
        if aware(row["timestamp"]).date() == day
        and START <= aware(row["timestamp"]).time() <= END
    }
    pv = volume = 0.0
    output = []
    for timestamp in sorted(set(index) & set(futures)):
        spot = index[timestamp]
        future = futures[timestamp]
        minute_volume = float(future.get("volume") or 0.0)
        pv += float(future["close"]) * minute_volume
        volume += minute_volume
        output.append(
            {
                "timestamp": timestamp,
                "underlying_open": spot["open"],
                "underlying_high": spot["high"],
                "underlying_low": spot["low"],
                "underlying_close": spot["close"],
                "futures_open": float(future["open"]),
                "futures_high": float(future["high"]),
                "futures_low": float(future["low"]),
                "futures_close": float(future["close"]),
                "futures_volume": minute_volume,
                "futures_vwap": pv / volume if volume else None,
            }
        )
    return validate_market(output, day), {
        "source": "UPSTOX_POST_SESSION_HISTORICAL_1M",
        "futures_instrument_key": contract.instrument_key,
        "futures_expiry": contract.expiry.isoformat(),
        "futures_source": contract.source,
        "vwap_basis": "CUMULATIVE_FUTURES_CLOSE_X_VOLUME",
    }


def market_rows(
    day: date, market_file: Path | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if market_file is not None:
        rows = normalize_cached(load_jsonl(market_file), day)
        return rows, {
            "source": "SUPPLIED_EXACT_MARKET_FILE",
            "path": str(market_file),
            "vwap_basis": "RECORDED",
        }
    return acquire_market(day)


def unique_entries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse C/rearm aliases that represent the same timestamp and direction."""
    groups: dict[tuple[str, str, float | None], list[dict[str, Any]]] = {}
    for event in events:
        if event.get("event_type") not in ENTRY_TYPES:
            continue
        price = event.get("underlying_price")
        key = (
            aware(event["event_timestamp"]).isoformat(),
            str(event.get("direction") or ""),
            round(float(price), 4) if price is not None else None,
        )
        groups.setdefault(key, []).append(event)
    output = []
    for members in groups.values():
        preferred = sorted(
            members,
            key=lambda row: (
                "REARM" in str(row.get("event_type")),
                str(row.get("event_type")),
            ),
        )[0]
        item = dict(preferred)
        item["entry_aliases"] = sorted({str(row["event_type"]) for row in members})
        output.append(item)
    return sorted(output, key=lambda row: aware(row["event_timestamp"]))


def directional_points(direction: str, entry: float, current: float) -> float:
    return current - entry if direction == "BULLISH" else entry - current


def health_series(rows: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    engine = MidpointEntryHealthLiveV1()
    output = {}
    for row in rows:
        output[row["timestamp"]] = engine.update(
            timestamp=row["timestamp"],
            open_=row["underlying_open"],
            high=row["underlying_high"],
            low=row["underlying_low"],
            close=row["underlying_close"],
            futures_open=row["futures_open"],
            futures_close=row["futures_close"],
            futures_vwap=row["futures_vwap"],
            futures_volume=row["futures_volume"],
        )
    return output


def checkpoint(
    timestamp: datetime,
    direction: str,
    entry_price: float,
    market: dict[datetime, dict[str, Any]],
    raw: dict[datetime, dict[str, Any]],
) -> dict[str, Any]:
    candle = market.get(timestamp)
    inputs = raw.get(timestamp)
    if candle is None or inputs is None:
        return {"timestamp": timestamp.isoformat(), "health": "UNAVAILABLE", "issue": "MINUTE_MISSING"}
    snapshot = MidpointEntryHealthLiveV1.directional_snapshot(inputs, direction)
    label = entry_health_label(snapshot)
    return {
        "timestamp": timestamp.isoformat(),
        "nifty_close": candle["underlying_close"],
        "directional_points": directional_points(
            direction, entry_price, candle["underlying_close"]
        ),
        **snapshot,
        **label,
    }


def event_in_segment(
    events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    event_type: str,
) -> dict[str, Any] | None:
    matches = [
        event for event in events
        if event.get("event_type") == event_type
        and start <= aware(event["event_timestamp"]) < end
    ]
    return min(matches, key=lambda row: aware(row["event_timestamp"])) if matches else None


def analyse(
    day: date,
    events: list[dict[str, Any]],
    market_rows_: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries = unique_entries(events)
    market = {row["timestamp"]: row for row in market_rows_}
    raw = health_series(market_rows_)
    session_end = datetime.combine(day, END, IST) + timedelta(minutes=1)
    output = []
    for index, entry in enumerate(entries):
        entry_at = aware(entry["event_timestamp"])
        end = (
            aware(entries[index + 1]["event_timestamp"])
            if index + 1 < len(entries) else session_end
        )
        direction = str(entry["direction"])
        entry_price = float(entry["underlying_price"])
        proof = event_in_segment(events, entry_at, end, "PLUS20_PROOF")
        classifier = event_in_segment(events, entry_at, end, "RUNNER_CLASSIFICATION")
        terminal = event_in_segment(events, entry_at, end, "STRUCTURAL_TERMINAL")
        moments: dict[str, datetime] = {
            "PREENTRY": entry_at - timedelta(minutes=1),
            "ENTRY": entry_at,
            "T3": entry_at + timedelta(minutes=3),
            "T5": entry_at + timedelta(minutes=5),
        }
        if proof is not None:
            moments["PROOF"] = aware(proof["event_timestamp"])
        if classifier is not None:
            moments["CLASSIFIER"] = aware(classifier["event_timestamp"])
        checkpoints = {
            name: checkpoint(moment, direction, entry_price, market, raw)
            for name, moment in moments.items()
        }

        t5_at = moments["T5"]
        proof_at = aware(proof["event_timestamp"]) if proof else None
        t5_snapshot = checkpoints["T5"]
        t5_decision = evaluate_t5_candidates(t5_snapshot)
        if proof_at is not None and proof_at <= t5_at:
            t5_status = "BYPASSED_ALREADY_PROVED"
        elif t5_decision.get("two_of_three") or t5_decision.get("combined_edge"):
            t5_status = "INITIAL_RISK_EXIT_CANDIDATE"
        elif not t5_decision.get("available"):
            t5_status = "UNAVAILABLE"
        else:
            t5_status = "CONTINUE"

        classifier_candidate = False
        if classifier is not None:
            evidence = classifier.get("evidence") or {}
            classifier_candidate = (
                classifier.get("result") == "NORMAL_B"
                and evidence.get("condition_progress_positive") is False
                and evidence.get("condition_vwap_change_positive") is False
            )
        historical_close = market.get(entry_at, {}).get("underlying_close")
        actual_exit_points = (
            directional_points(direction, entry_price, float(terminal["underlying_price"]))
            if terminal and terminal.get("underlying_price") is not None else None
        )
        output.append(
            {
                "session_date": day.isoformat(),
                "family": entry.get("family"),
                "entry_event": entry.get("event_type"),
                "entry_aliases": entry["entry_aliases"],
                "direction": direction,
                "entry_timestamp": entry_at.isoformat(),
                "audit_entry_price": entry_price,
                "historical_entry_close": historical_close,
                "entry_close_revision": (
                    historical_close - entry_price if historical_close is not None else None
                ),
                "plus20_timestamp": proof_at.isoformat() if proof_at else None,
                "classifier_timestamp": (
                    aware(classifier["event_timestamp"]).isoformat() if classifier else None
                ),
                "classifier_result": classifier.get("result") if classifier else None,
                "terminal_timestamp": (
                    aware(terminal["event_timestamp"]).isoformat() if terminal else None
                ),
                "actual_exit_points": actual_exit_points,
                "checkpoints": checkpoints,
                "t5_decision": {**t5_decision, "status": t5_status},
                "classifier_dual_failure_candidate": classifier_candidate,
                "classifier_close_points": (
                    checkpoints.get("CLASSIFIER", {}).get("directional_points")
                    if classifier_candidate else None
                ),
                "interpretation": (
                    "MANAGE_PROVED_TRADE_NOT_ENTRY_AVOIDANCE"
                    if proof is not None
                    else "INITIAL_RISK_RESEARCH_CANDIDATE"
                ),
            }
        )
    return output


def write_summary(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "session_date", "family", "entry_event", "entry_aliases", "direction",
        "entry_timestamp", "audit_entry_price", "historical_entry_close",
        "entry_close_revision", "plus20_timestamp", "classifier_timestamp",
        "classifier_result", "terminal_timestamp", "actual_exit_points",
        "preentry_health", "entry_health", "t3_health", "t5_health",
        "t5_status", "t5_points", "classifier_dual_failure_candidate",
        "classifier_close_points", "interpretation",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow(
                {
                    **{name: trade.get(name) for name in fields},
                    "entry_aliases": ",".join(trade["entry_aliases"]),
                    "preentry_health": trade["checkpoints"]["PREENTRY"]["health"],
                    "entry_health": trade["checkpoints"]["ENTRY"]["health"],
                    "t3_health": trade["checkpoints"]["T3"]["health"],
                    "t5_health": trade["checkpoints"]["T5"]["health"],
                    "t5_status": trade["t5_decision"]["status"],
                    "t5_points": trade["checkpoints"]["T5"].get("directional_points"),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", type=date.fromisoformat, required=True)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--market-file", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    arguments = parser.parse_args()
    output = arguments.output_root / arguments.session_date.isoformat()
    if output.exists():
        raise SystemExit(
            f"STOP: immutable diagnostic output already exists: {output}. "
            "Use a new --output-root to rerun."
        )
    events = [
        row for row in load_jsonl(arguments.audit)
        if row.get("session_date") == arguments.session_date.isoformat()
    ]
    if not events:
        raise SystemExit(f"STOP: no audit events for {arguments.session_date}")
    rows, metadata = market_rows(arguments.session_date, arguments.market_file)
    trades = analyse(arguments.session_date, events, rows)
    if not trades:
        raise SystemExit(f"STOP: no Midpoint entries for {arguments.session_date}")
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(
        output / "market-minutes.jsonl",
        [
            {**row, "timestamp": row["timestamp"].isoformat()}
            for row in rows
        ],
    )
    report = {
        "model": "MIDPOINT_SESSION_HEALTH_DIAGNOSTIC_V1",
        "session_date": arguments.session_date.isoformat(),
        "market": metadata,
        "trades": trades,
        "limitations": [
            "Post-session broker candles can differ from immutable live candles.",
            "Health is reconstructed causally with the current live health engine.",
            "Candidate exits are counterfactual and do not alter strategy state.",
        ],
        "safety": {
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    write_summary(output / "summary.csv", trades)
    print("MIDPOINT SESSION HEALTH", arguments.session_date)
    print("market:", metadata)
    for trade in trades:
        print(
            "\nTRADE",
            trade["entry_timestamp"], trade["entry_aliases"],
            trade["direction"], "actual", trade["actual_exit_points"],
        )
        for name, value in trade["checkpoints"].items():
            print(
                " ", name, value["timestamp"], value["health"],
                f"support={value.get('support_count')}",
                f"points={value.get('directional_points')}",
                f"DI={value.get('directional_di_spread')}",
                f"edge={value.get('combined_edge')}",
                f"momentum={value.get('price_momentum_support')}",
            )
        print("  T5", trade["t5_decision"])
        print(
            "  CLASSIFIER_DUAL_FAILURE",
            trade["classifier_dual_failure_candidate"],
            "close_points", trade["classifier_close_points"],
        )
        print("  INTERPRETATION", trade["interpretation"])
    print("\nOutput:", output / "report.json")
    print("Read only: live audit, configuration, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
