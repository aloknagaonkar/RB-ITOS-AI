from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median

RESEARCH_VERSION = "MIDPOINT_V2_OI_FUTURES_VWAP_CONFLUENCE_V1_FIX1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def metric_summary(values):
    values = [float(x) for x in values]
    if not values:
        return {
            "trade_count": 0,
            "winner_count": 0,
            "win_rate_pct": None,
            "mean_net_pct": None,
            "median_net_pct": None,
            "sum_net_pct_points": None,
            "profit_factor": None,
            "average_winner_pct": None,
            "average_loser_pct": None,
            "best_trade_pct": None,
            "worst_trade_pct": None,
        }

    winners = [x for x in values if x > 0]
    losers = [x for x in values if x <= 0]
    gp = sum(winners)
    gl = abs(sum(losers))

    return {
        "trade_count": len(values),
        "winner_count": len(winners),
        "win_rate_pct": 100.0 * len(winners) / len(values),
        "mean_net_pct": mean(values),
        "median_net_pct": median(values),
        "sum_net_pct_points": sum(values),
        "profit_factor": gp / gl if gl > 0 else None,
        "average_winner_pct": mean(winners) if winners else None,
        "average_loser_pct": mean(losers) if losers else None,
        "best_trade_pct": max(values),
        "worst_trade_pct": min(values),
    }


def load_futures_vwap(path: Path):
    idx = {}

    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)

        required = {
            "session_date",
            "timestamp",
            "close",
            "session_vwap",
            "instrument_key",
            "expiry",
        }

        headers = set(rd.fieldnames or [])
        missing = required - headers
        if missing:
            raise ValueError(
                f"Futures VWAP CSV missing required columns: {sorted(missing)}"
            )

        for row in rd:
            key = (str(row["session_date"]), str(row["timestamp"]))

            if key in idx:
                raise ValueError(
                    f"Duplicate futures VWAP row for session/timestamp: {key}"
                )

            idx[key] = {
                "close": float(row["close"]),
                "vwap": float(row["session_vwap"]),
                "instrument_key": str(row["instrument_key"]),
                "expiry": str(row["expiry"]),
                "contract_source": row.get("contract_source"),
            }

    return idx


def load_confirmed_trades(economics_doc):
    """
    FIX1:
    Use the canonical exact-option economics 'trades' array directly.

    The stable state-machine event artifact does not carry t3_timestamp on its
    event rows, while exact-option economics already contains:
      block
      session_date
      direction
      setup_type
      t3_state
      t3_timestamp
      oi_quality
      exact_oi_transition_t1_to_t3
      exact option economics

    This avoids schema guessing and does not reconstruct or relabel OI.
    """
    trades = economics_doc.get("trades")
    if not isinstance(trades, list):
        raise ValueError(
            "Exact-option economics artifact does not contain a top-level "
            "'trades' list"
        )

    result = []

    for row in trades:
        if not isinstance(row, dict):
            continue

        block = str(row.get("block") or "")
        if block not in ALLOWED_BLOCKS:
            continue

        if str(row.get("t3_state") or "") != "CONFIRM_CONTINUATION":
            continue

        if not row.get("entry_available"):
            continue

        if not row.get("complete_15m_path"):
            continue

        direction = str(row.get("direction") or "")
        if direction not in {"BULLISH", "BEARISH"}:
            continue

        session_date = str(row.get("session_date") or "")
        t3_timestamp = str(row.get("t3_timestamp") or "")

        if not session_date or not t3_timestamp:
            continue

        net_returns = row.get("net_returns_pct") or {}
        net_15m = net_returns.get("15m")

        if net_15m is None:
            continue

        oi_quality = str(row.get("oi_quality") or "").upper()

        result.append({
            "block": block,
            "session_date": session_date,
            "direction": direction,
            "setup_type": row.get("setup_type"),
            "t3_state": row.get("t3_state"),
            "t3_timestamp": t3_timestamp,
            "oi_quality": oi_quality,
            "exact_oi_transition_t1_to_t3": row.get(
                "exact_oi_transition_t1_to_t3"
            ),
            "instrument_key": row.get("instrument_key"),
            "option_side": row.get("option_side"),
            "entry_timestamp": row.get("entry_timestamp"),
            "entry_price": row.get("entry_price"),
            "net_15m_pct": float(net_15m),
            "mfe_pct_15m": row.get("mfe_pct_15m"),
            "mae_pct_15m": row.get("mae_pct_15m"),
        })

    return result


def block_summary(rows, predicate):
    out = {}

    for block in sorted(ALLOWED_BLOCKS):
        values = [
            row["net_15m_pct"]
            for row in rows
            if row["block"] == block and predicate(row)
        ]
        out[block] = metric_summary(values)

    return out


def main():
    ap = argparse.ArgumentParser()

    # Kept for command compatibility, but FIX1 deliberately does not parse
    # state-machine events because their canonical event rows do not carry
    # t3_timestamp.
    ap.add_argument("--events", required=False)

    ap.add_argument("--economics", required=True)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--output", required=True)

    args = ap.parse_args()

    economics_doc = load_json(Path(args.economics))
    futures_idx = load_futures_vwap(Path(args.futures_vwap))
    trades = load_confirmed_trades(economics_doc)

    joined = []
    missing_futures = []

    for trade in trades:
        fkey = (trade["session_date"], trade["t3_timestamp"])
        fut = futures_idx.get(fkey)

        if fut is None:
            missing_futures.append({
                "block": trade["block"],
                "session_date": trade["session_date"],
                "direction": trade["direction"],
                "t3_timestamp": trade["t3_timestamp"],
            })
            continue

        direction = trade["direction"]

        vwap_aligned = (
            (direction == "BULLISH" and fut["close"] > fut["vwap"])
            or
            (direction == "BEARISH" and fut["close"] < fut["vwap"])
        )

        # Canonical existing OI quality semantics:
        # oi_quality == STRONG means OI strongly supports the event direction.
        # We do not derive a new direction from option OI here.
        strong_oi_aligned = trade["oi_quality"] == "STRONG"

        joined.append({
            **trade,
            "strong_oi_aligned": strong_oi_aligned,
            "futures_close": fut["close"],
            "futures_vwap": fut["vwap"],
            "futures_vwap_distance_points": fut["close"] - fut["vwap"],
            "futures_vwap_aligned": vwap_aligned,
            "strong_oi_plus_futures_vwap_aligned": (
                strong_oi_aligned and vwap_aligned
            ),
            "futures_instrument_key": fut["instrument_key"],
            "futures_expiry": fut["expiry"],
            "futures_contract_source": fut["contract_source"],
        })

    all_sel = lambda row: True
    oi_sel = lambda row: row["strong_oi_aligned"]
    vwap_sel = lambda row: row["futures_vwap_aligned"]
    both_sel = lambda row: row["strong_oi_plus_futures_vwap_aligned"]

    all_values = [r["net_15m_pct"] for r in joined]
    oi_values = [r["net_15m_pct"] for r in joined if oi_sel(r)]
    vwap_values = [r["net_15m_pct"] for r in joined if vwap_sel(r)]
    both_values = [r["net_15m_pct"] for r in joined if both_sel(r)]

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_contract": {
            "event_source": (
                "midpoint-v3-2 exact-option economics canonical trades array"
            ),
            "state_machine_events_reparsed": False,
            "oi_source": "existing trade.oi_quality",
            "oi_strong_definition": (
                "oi_quality == STRONG; this is existing aligned OI quality, "
                "not a newly derived OI direction"
            ),
            "pnl_metric": (
                "existing exact-option net_returns_pct['15m']; "
                "0.5 percentage-point cost already included"
            ),
            "futures_source": (
                "exact active NIFTY FUT 1-minute OHLCV with prospective "
                "cumulative session VWAP"
            ),
        },
        "rules": {
            "trigger": "existing T+3 CONFIRM_CONTINUATION only",
            "bullish_vwap_pass": "NIFTY FUT close > session VWAP at T+3",
            "bearish_vwap_pass": "NIFTY FUT close < session VWAP at T+3",
            "strong_oi_pass": "existing oi_quality == STRONG",
            "combined_pass": "strong OI and futures VWAP aligned",
            "no_vwap_slope": True,
            "no_vwap_distance_threshold": True,
            "no_second_bar_confirmation": True,
            "no_stop_change": True,
            "no_entry_timing_change": True,
            "no_oi_reclassification": True,
        },
        "summary": {
            "confirmed_exact_option_trade_count": len(trades),
            "joined_trade_count": len(joined),
            "missing_futures_vwap_count": len(missing_futures),
            "all_confirmed": metric_summary(all_values),
            "strong_oi_only": metric_summary(oi_values),
            "futures_vwap_only": metric_summary(vwap_values),
            "strong_oi_plus_futures_vwap": metric_summary(both_values),
            "counts": {
                "strong_oi_aligned": sum(
                    1 for r in joined if r["strong_oi_aligned"]
                ),
                "futures_vwap_aligned": sum(
                    1 for r in joined if r["futures_vwap_aligned"]
                ),
                "strong_oi_plus_futures_vwap_aligned": sum(
                    1
                    for r in joined
                    if r["strong_oi_plus_futures_vwap_aligned"]
                ),
            },
        },
        "block_summaries": {
            "all_confirmed": block_summary(joined, all_sel),
            "strong_oi_only": block_summary(joined, oi_sel),
            "futures_vwap_only": block_summary(joined, vwap_sel),
            "strong_oi_plus_futures_vwap": block_summary(joined, both_sel),
        },
        "direction_summaries": {
            direction: {
                "all_confirmed": metric_summary([
                    r["net_15m_pct"]
                    for r in joined
                    if r["direction"] == direction
                ]),
                "strong_oi_only": metric_summary([
                    r["net_15m_pct"]
                    for r in joined
                    if r["direction"] == direction
                    and r["strong_oi_aligned"]
                ]),
                "futures_vwap_only": metric_summary([
                    r["net_15m_pct"]
                    for r in joined
                    if r["direction"] == direction
                    and r["futures_vwap_aligned"]
                ]),
                "strong_oi_plus_futures_vwap": metric_summary([
                    r["net_15m_pct"]
                    for r in joined
                    if r["direction"] == direction
                    and r["strong_oi_plus_futures_vwap_aligned"]
                ]),
            }
            for direction in ("BULLISH", "BEARISH")
        },
        "sep7_reference": next(
            (
                r
                for r in joined
                if r["session_date"] == "2026-09-07"
            ),
            None,
        ),
        "missing_futures_vwap": missing_futures,
        "rows": joined,
        "governance": {
            "development_research_only": True,
            "allowed_blocks": sorted(ALLOWED_BLOCKS),
            "e_f_g_h_used": False,
            "v1_freeze_changed": False,
            "no_rule_promoted": True,
            "fresh_oos_required_before_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
