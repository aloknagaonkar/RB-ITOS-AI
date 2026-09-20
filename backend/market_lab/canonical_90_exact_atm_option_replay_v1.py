from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from market_lab.structure_price_lag_option_exit_validation_v1 import (
    POLICIES,
    ROUND_TRIP_COST_PCT_POINTS,
    replay_policy,
)

MODEL = "CANONICAL_90_EXACT_ATM_OPTION_REPLAY_V1"
POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"

DEFAULT_COVERAGE = Path(
    "data/historical-evidence/canonical-90-exact-atm-option-coverage-v1.json"
)
DEFAULT_EVIDENCE_ROOT = Path("data/historical-evidence")
DEFAULT_OUTPUT_JSON = Path(
    "data/historical-evidence/canonical-90-exact-atm-option-replay-v1.json"
)
DEFAULT_OUTPUT_CSV = Path(
    "data/historical-evidence/canonical-90-exact-atm-option-replay-v1.csv"
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _num(value: Any) -> float | None:
    if value in (None, "", "NA"):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [r for r in rows if r.get("available") is True]
    vals = [float(r["net_return_pct"]) for r in available]
    winners = [v for v in vals if v > 0]
    losers = [v for v in vals if v <= 0]

    return {
        "candidate_count": len(rows),
        "available_count": len(available),
        "unavailable_count": len(rows) - len(available),
        "winner_count": len(winners),
        "loser_or_flat_count": len(losers),
        "win_rate_pct": (100.0 * len(winners) / len(vals)) if vals else None,
        "mean_net_pct": statistics.fmean(vals) if vals else None,
        "median_net_pct": statistics.median(vals) if vals else None,
        "sum_net_pct_points": sum(vals) if vals else None,
        "profit_factor": _profit_factor(vals),
        "average_winner_pct": statistics.fmean(winners) if winners else None,
        "average_loser_pct": statistics.fmean(losers) if losers else None,
        "best_trade_pct": max(vals) if vals else None,
        "worst_trade_pct": min(vals) if vals else None,
        "exit_reason_counts": dict(Counter(
            r.get("exit_reason") for r in available
        )),
        "be_armed_count": sum(r.get("be_armed") is True for r in available),
        "trail_armed_count": sum(r.get("trail_armed") is True for r in available),
    }


def load_coverage(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc.get("rows"), list):
        raise ValueError("coverage artifact missing top-level rows list")
    return doc


def _option_file_for_block(root: Path, block: str) -> Path:
    if block == "TRAIN":
        p = root / "option-ohlc-train.csv"
    else:
        suffix = block.lower().replace("_", "-")
        p = root / f"option-ohlc-{suffix}.csv"
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(f"option OHLC file missing/empty for {block}: {p}")
    return p


def _required_windows(rows: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    """
    block -> instrument -> exact replay timestamps needed by the frozen engine.

    replay_policy checks entry+1 .. entry+15. Entry OPEN itself is already
    frozen in the coverage artifact and is identity-checked separately.
    """
    need: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        block = str(row["block"])
        instrument = str(row["instrument_key"])
        start = _dt(row["entry_timestamp"])
        for minute in range(1, 16):
            need[block][instrument].add(
                (start + timedelta(minutes=minute)).isoformat()
            )
    return need


def load_needed_ohlc(
    rows: list[dict[str, Any]],
    evidence_root: str | Path,
) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    """
    Stream only the exact instruments/timestamps required by READY trades.

    Result shape matches replay_policy's index:
      block -> instrument_key -> timestamp -> raw OHLC row
    """
    root = Path(evidence_root)
    need = _required_windows(rows)
    out: dict[str, dict[str, dict[str, dict[str, str]]]] = {}

    for block, by_instrument in sorted(need.items()):
        p = _option_file_for_block(root, block)
        block_idx: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

        with p.open(newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            required = {
                "session_date", "instrument_key", "timestamp",
                "open", "high", "low", "close",
            }
            missing = required - set(rd.fieldnames or [])
            if missing:
                raise ValueError(f"{p}: missing columns {sorted(missing)}")

            for raw in rd:
                instrument = str(raw.get("instrument_key") or "")
                wanted = by_instrument.get(instrument)
                if not wanted:
                    continue
                ts = str(raw.get("timestamp") or "")
                if ts in wanted:
                    block_idx[instrument][ts] = raw

        out[block] = dict(block_idx)

    return out


def replay_ready_rows(
    coverage_rows: list[dict[str, Any]],
    idx_by_block: dict[str, dict[str, dict[str, dict[str, str]]]],
) -> list[dict[str, Any]]:
    policy = POLICIES[POLICY_ID]
    results: list[dict[str, Any]] = []

    for src in coverage_rows:
        if src.get("coverage_status") != "READY":
            continue

        block = str(src["block"])
        trade = {
            "instrument_key": str(src["instrument_key"]),
            "entry_timestamp": str(src["entry_timestamp"]),
            "entry_open": float(src["entry_open"]),
        }

        result = replay_policy(
            trade,
            idx_by_block.get(block, {}),
            POLICY_ID,
            policy,
        )

        base = {
            "event_id": src["event_id"],
            "session_date": src["session_date"],
            "block": block,
            "direction": src["direction"],
            "c1_timestamp": src.get("c1_timestamp"),
            "c2_timestamp": src.get("c2_expected_timestamp"),
            "futures_state": src.get("futures_state"),
            "option_side": src["option_side"],
            "strike": src["strike"],
            "moving_atm": src.get("moving_atm"),
            "instrument_key": src["instrument_key"],
            "entry_timestamp": src["entry_timestamp"],
            "entry_open": src["entry_open"],
            "coverage_status": src["coverage_status"],
        }

        if result is None:
            base.update({
                "policy_id": POLICY_ID,
                "available": False,
                "issue": "REPLAY_FAILED",
            })
        else:
            base.update(result)

        results.append(base)

    results.sort(
        key=lambda r: (
            r["session_date"],
            r["entry_timestamp"],
            str(r["event_id"]),
        )
    )
    return results


def write_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "event_id","session_date","block","direction",
        "c1_timestamp","c2_timestamp","futures_state",
        "option_side","strike","moving_atm","instrument_key",
        "entry_timestamp","entry_open","policy_id","available","issue",
        "entry_price","exit_timestamp","exit_price","exit_reason",
        "gross_return_pct","net_return_pct","bars_seen",
        "be_armed","trail_armed",
    ]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run(
    *,
    coverage_path: str | Path = DEFAULT_COVERAGE,
    evidence_root: str | Path = DEFAULT_EVIDENCE_ROOT,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_csv: str | Path = DEFAULT_OUTPUT_CSV,
) -> dict[str, Any]:
    coverage = load_coverage(coverage_path)
    ready = [r for r in coverage["rows"] if r.get("coverage_status") == "READY"]
    censored = [
        r for r in coverage["rows"]
        if r.get("coverage_status") == "SESSION_END_CENSORED"
    ]

    idx = load_needed_ohlc(ready, evidence_root)
    trades = replay_ready_rows(ready, idx)

    overall = _summary(trades)
    by_direction = {
        d: _summary([r for r in trades if r["direction"] == d])
        for d in ("BULLISH", "BEARISH")
    }
    by_block = {
        b: _summary([r for r in trades if r["block"] == b])
        for b in sorted({r["block"] for r in trades})
    }

    result = {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_REPLAY_ON_EXPOSED_CANONICAL_90_POPULATION",
        "strategy_logic_changed": False,
        "entry_logic_changed": False,
        "threshold_optimization": False,
        "coverage_source": str(coverage_path),
        "eligible_signal_count": len(coverage["rows"]),
        "replayable_ready_count": len(ready),
        "session_end_censored_count": len(censored),
        "replayed_trade_count": len(trades),
        "policy_id": POLICY_ID,
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "execution_semantics": {
            "entry": "EXACT_NEXT_MINUTE_OPEN_AFTER_C2",
            "contract": "EXACT_MOVING_ATM_CE_IF_BULLISH_PE_IF_BEARISH",
            "nearest_strike_fallback": False,
            "nearest_time_fallback": False,
            "intrabar_stop_resolution": "OPEN_GAP_THEN_LOW_TOUCH",
            "breakeven_and_trail_activation": "NEXT_BAR_ONLY",
            "time_exit": "EXACT_ENTRY_PLUS_15_MINUTE_CLOSE",
        },
        "policy": dict(POLICIES[POLICY_ID]),
        "summary": overall,
        "by_direction": by_direction,
        "by_block": by_block,
        "excluded_session_end_censored": [
            {
                "event_id": r["event_id"],
                "session_date": r["session_date"],
                "direction": r["direction"],
                "c2_timestamp": r.get("c2_expected_timestamp"),
                "entry_timestamp": r.get("entry_timestamp"),
                "instrument_key": r.get("instrument_key"),
                "strike": r.get("strike"),
                "coverage_status": r.get("coverage_status"),
                "missing_timestamps": r.get("missing_timestamps", []),
            }
            for r in censored
        ],
        "trades": trades,
        "governance": {
            "population_is_fresh_oos": False,
            "population_previously_exposed": True,
            "result_is_strategy_validation": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(trades, output_csv)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", default=str(DEFAULT_COVERAGE))
    ap.add_argument("--evidence-root", default=str(DEFAULT_EVIDENCE_ROOT))
    ap.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    ap.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    args = ap.parse_args()

    r = run(
        coverage_path=args.coverage,
        evidence_root=args.evidence_root,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )
    print(json.dumps({
        "status": r["status"],
        "model": r["model"],
        "eligible_signal_count": r["eligible_signal_count"],
        "replayable_ready_count": r["replayable_ready_count"],
        "session_end_censored_count": r["session_end_censored_count"],
        "replayed_trade_count": r["replayed_trade_count"],
        "policy_id": r["policy_id"],
        "summary": r["summary"],
        "by_direction": r["by_direction"],
        "by_block": r["by_block"],
        "output_json": args.output_json,
        "output_csv": args.output_csv,
    }, indent=2))


if __name__ == "__main__":
    main()
