from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_REBREAK_EXACT_OPTION_REPLAY_V1_FIX1"
EXPECTED_DIAGNOSTIC_VERSION = "MIDPOINT_V2_BREAK_AND_GO_REBREAK_REENTRY_DIAGNOSTICS_V1_FIX1"
POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"

INITIAL_STOP_PCT = 5.0
BE_TRIGGER_PCT = 5.0
TRAIL_TRIGGER_PCT = 10.0
TRAIL_DISTANCE_PCT = 3.0
MAX_HOLD_MINUTES = 15
ROUND_TRIP_COST_PCT_POINTS = 0.5


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def ffloat(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def first_existing(headers, names):
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    raise ValueError(f"missing one of {names}; available={headers}")


def optional_existing(headers, names):
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def parse_block_specs(specs, loader):
    out = {}
    for spec in specs:
        if "|" not in spec:
            raise ValueError("expected BLOCK|path")
        block, raw = spec.split("|", 1)
        out[block.strip()] = loader(Path(raw.strip()))
    return out


def load_positioning(path: Path):
    """
    Supports both schemas:

    LONG / one-option-per-row:
      timestamp,instrument_key,strike,option_type,...

    WIDE / CE+PE on one row:
      timestamp,moving_atm,strike,ce_instrument_key,pe_instrument_key,...

    For the wide schema we emit the PE leg directly because this replay is
    bearish-only and requires an exact ATM PE.
    """
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        headers = list(rd.fieldnames or [])
        lower = {h.lower(): h for h in headers}

        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts"))

        # Wide schema detection first.
        pe_key_col = optional_existing(headers, ("pe_instrument_key", "put_instrument_key"))
        moving_atm_col = optional_existing(headers, ("moving_atm", "atm", "atm_strike"))
        strike_col = optional_existing(headers, ("strike", "strike_price"))

        if pe_key_col is not None:
            if moving_atm_col is None and strike_col is None:
                raise ValueError(
                    "wide positioning schema found pe_instrument_key but no moving_atm/strike"
                )
            for r in rd:
                raw = r.get(ts_col)
                inst = r.get(pe_key_col)
                if not raw or not inst:
                    continue
                try:
                    ts = parse_dt(raw)
                except ValueError:
                    continue

                strike = ffloat(r.get(moving_atm_col)) if moving_atm_col else None
                if strike is None and strike_col:
                    strike = ffloat(r.get(strike_col))
                if strike is None:
                    continue

                rows.append({
                    "timestamp": ts.isoformat(),
                    "instrument_key": str(inst),
                    "strike": strike,
                    "option_type": "PE",
                })
            return rows

        # Long schema fallback.
        inst_col = first_existing(headers, ("instrument_key", "instrument", "instrument_token"))
        strike_col = first_existing(headers, ("strike", "strike_price"))
        type_col = first_existing(headers, ("option_type", "right", "type", "instrument_type"))

        for r in rd:
            raw = r.get(ts_col)
            inst = r.get(inst_col)
            if not raw or not inst:
                continue
            try:
                ts = parse_dt(raw)
            except ValueError:
                continue
            strike = ffloat(r.get(strike_col))
            if strike is None:
                continue
            rows.append({
                "timestamp": ts.isoformat(),
                "instrument_key": str(inst),
                "strike": strike,
                "option_type": str(r.get(type_col)).upper(),
            })
    return rows


def load_option_ohlc(path: Path):
    out = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        headers = list(rd.fieldnames or [])
        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts"))
        inst_col = first_existing(headers, ("instrument_key", "instrument", "instrument_token"))
        open_col = first_existing(headers, ("open", "o"))
        high_col = first_existing(headers, ("high", "h"))
        low_col = first_existing(headers, ("low", "l"))
        close_col = first_existing(headers, ("close", "c"))
        for r in rd:
            raw = r.get(ts_col)
            inst = r.get(inst_col)
            if not raw or not inst:
                continue
            try:
                ts = parse_dt(raw)
            except ValueError:
                continue
            vals = {
                "open": ffloat(r.get(open_col)),
                "high": ffloat(r.get(high_col)),
                "low": ffloat(r.get(low_col)),
                "close": ffloat(r.get(close_col)),
            }
            if any(v is None for v in vals.values()):
                continue
            out[(str(inst), ts.isoformat())] = vals
    return out


def nearest_50(x: float) -> int:
    return int(round(x / 50.0) * 50)


def is_pe(v: str) -> bool:
    u = v.upper()
    return u in {"PE", "PUT", "P", "OPTPE"} or u.endswith("PE")


def select_exact_atm_pe(positioning_rows, confirmation_ts: str, underlying_close: float):
    target_strike = nearest_50(underlying_close)
    candidates = [
        r for r in positioning_rows
        if r["timestamp"] == confirmation_ts
        and is_pe(r["option_type"])
        and int(round(r["strike"])) == target_strike
    ]
    if len(candidates) == 1:
        return {
            "available": True,
            "issue": None,
            "atm_strike": target_strike,
            "instrument_key": candidates[0]["instrument_key"],
        }
    if len(candidates) == 0:
        return {
            "available": False,
            "issue": "EXACT_ATM_PE_NOT_FOUND",
            "atm_strike": target_strike,
            "instrument_key": None,
        }
    return {
        "available": False,
        "issue": "AMBIGUOUS_EXACT_ATM_PE",
        "atm_strike": target_strike,
        "instrument_key": None,
        "candidate_count": len(candidates),
    }


def replay_frozen_exit(option_market, instrument_key: str, entry_ts: datetime, entry_price: float):
    initial_stop = entry_price * (1.0 - INITIAL_STOP_PCT / 100.0)
    active_stop = initial_stop
    active_regime = "INITIAL_SL5"
    pending_be = False
    pending_trail = False
    trailing_high = None

    for minute in range(MAX_HOLD_MINUTES + 1):
        ts = entry_ts + timedelta(minutes=minute)
        bar = option_market.get((instrument_key, ts.isoformat()))
        if bar is None:
            return {"available": False, "issue": f"MISSING_OPTION_BAR_{minute}M"}

        o, h, l, c = map(float, (bar["open"], bar["high"], bar["low"], bar["close"]))

        if pending_be:
            active_stop = max(active_stop, entry_price)
            active_regime = "BREAKEVEN"
            pending_be = False

        if pending_trail:
            trailing_high = max(trailing_high or h, h)
            active_stop = max(active_stop, trailing_high * (1.0 - TRAIL_DISTANCE_PCT / 100.0))
            active_regime = "TRAILING"
            pending_trail = False
        elif active_regime == "TRAILING":
            trailing_high = max(trailing_high or h, h)
            active_stop = max(active_stop, trailing_high * (1.0 - TRAIL_DISTANCE_PCT / 100.0))

        if o <= active_stop:
            exit_price = o
            gross = (exit_price / entry_price - 1.0) * 100.0
            return {
                "available": True,
                "exit_reason": "STOP_GAP",
                "exit_regime": active_regime,
                "exit_timestamp": ts.isoformat(),
                "exit_price": exit_price,
                "gross_return_pct": gross,
                "net_return_pct": gross - ROUND_TRIP_COST_PCT_POINTS,
                "duration_minutes": minute,
            }

        if l <= active_stop:
            exit_price = active_stop
            gross = (exit_price / entry_price - 1.0) * 100.0
            return {
                "available": True,
                "exit_reason": "STOP_TOUCH",
                "exit_regime": active_regime,
                "exit_timestamp": ts.isoformat(),
                "exit_price": exit_price,
                "gross_return_pct": gross,
                "net_return_pct": gross - ROUND_TRIP_COST_PCT_POINTS,
                "duration_minutes": minute,
            }

        high_ret = (h / entry_price - 1.0) * 100.0
        if active_regime == "INITIAL_SL5" and high_ret >= BE_TRIGGER_PCT:
            pending_be = True
        if high_ret >= TRAIL_TRIGGER_PCT:
            pending_trail = True
            trailing_high = max(trailing_high or h, h)

        if minute == MAX_HOLD_MINUTES:
            exit_price = c
            gross = (exit_price / entry_price - 1.0) * 100.0
            return {
                "available": True,
                "exit_reason": "TIME_EXIT",
                "exit_regime": active_regime,
                "exit_timestamp": ts.isoformat(),
                "exit_price": exit_price,
                "gross_return_pct": gross,
                "net_return_pct": gross - ROUND_TRIP_COST_PCT_POINTS,
                "duration_minutes": minute,
            }

    raise AssertionError("unreachable")


def summarize(rows):
    avail = [r for r in rows if r["reentry_economics"].get("available")]
    returns = [r["reentry_economics"]["exit"]["net_return_pct"] for r in avail]
    winners = [x for x in returns if x > 0]
    losers = [x for x in returns if x <= 0]

    return {
        "structural_candidate_count": len(rows),
        "exact_reentry_available_count": len(avail),
        "issue_counts": dict(Counter(
            r["reentry_economics"].get("issue")
            for r in rows if not r["reentry_economics"].get("available")
        )),
        "winner_count": len(winners),
        "win_rate_pct": (100.0 * len(winners) / len(avail)) if avail else None,
        "mean_net_pct": mean(returns) if returns else None,
        "median_net_pct": median(returns) if returns else None,
        "sum_net_pct_points": sum(returns) if returns else None,
        "average_winner_pct": mean(winners) if winners else None,
        "average_loser_pct": mean(losers) if losers else None,
        "best_trade_pct": max(returns) if returns else None,
        "worst_trade_pct": min(returns) if returns else None,
        "exit_reason_counts": dict(Counter(
            r["reentry_economics"]["exit"]["exit_reason"] for r in avail
        )),
        "exit_regime_counts": dict(Counter(
            r["reentry_economics"]["exit"]["exit_regime"] for r in avail
        )),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostic", required=True)
    ap.add_argument("--positioning", action="append", required=True)
    ap.add_argument("--option-ohlc", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    diag = load_json(Path(args.diagnostic))
    if diag.get("research_version") != EXPECTED_DIAGNOSTIC_VERSION:
        raise SystemExit(f"unexpected diagnostic version={diag.get('research_version')!r}")

    positioning = parse_block_specs(args.positioning, load_positioning)
    option_ohlc = parse_block_specs(args.option_ohlc, load_option_ohlc)

    structural = [
        r for r in (diag.get("rows") or [])
        if r.get("eligible_initial_sl5") is True
        and (r.get("rebreak") or {}).get("rebreak_class") == "REBREAK_HELD_2_CLOSES"
    ]

    rows = []
    for r in structural:
        block = str(r["block"])
        rb = r["rebreak"]
        confirmation_ts = parse_dt(rb["rebreak_timestamp"]) + timedelta(minutes=1)
        confirmation_close = float(rb["next_close"])
        entry_ts = confirmation_ts + timedelta(minutes=1)

        selected = select_exact_atm_pe(
            positioning.get(block, []),
            confirmation_ts.isoformat(),
            confirmation_close,
        )

        if not selected["available"]:
            econ = {
                "available": False,
                "issue": selected["issue"],
                "confirmation_timestamp": confirmation_ts.isoformat(),
                "confirmation_underlying_close": confirmation_close,
                "atm_strike": selected.get("atm_strike"),
            }
        else:
            inst = selected["instrument_key"]
            entry_bar = option_ohlc.get(block, {}).get((inst, entry_ts.isoformat()))
            if entry_bar is None:
                econ = {
                    "available": False,
                    "issue": "EXACT_NEXT_MINUTE_OPEN_MISSING",
                    "confirmation_timestamp": confirmation_ts.isoformat(),
                    "confirmation_underlying_close": confirmation_close,
                    "atm_strike": selected["atm_strike"],
                    "instrument_key": inst,
                    "entry_timestamp": entry_ts.isoformat(),
                }
            else:
                entry_price = float(entry_bar["open"])
                exit_result = replay_frozen_exit(
                    option_ohlc.get(block, {}),
                    inst,
                    entry_ts,
                    entry_price,
                )
                econ = {
                    "available": bool(exit_result.get("available")),
                    "issue": exit_result.get("issue"),
                    "confirmation_timestamp": confirmation_ts.isoformat(),
                    "confirmation_underlying_close": confirmation_close,
                    "atm_strike": selected["atm_strike"],
                    "instrument_key": inst,
                    "entry_timestamp": entry_ts.isoformat(),
                    "entry_price": entry_price,
                    "exit": exit_result if exit_result.get("available") else None,
                }

        rows.append({
            "block": block,
            "session_date": r["session_date"],
            "original_reference_low": r["reference_low"],
            "original_frozen_exit": r["frozen_exit"],
            "rebreak": rb,
            "reentry_rule": {
                "first_rebreak_close": rb["rebreak_timestamp"],
                "second_held_close_confirmation": confirmation_ts.isoformat(),
                "entry": "EXACT_MOVING_ATM_PE_AT_CONFIRMATION_THEN_NEXT_MINUTE_OPEN",
            },
            "reentry_economics": econ,
        })

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_diagnostic_version": diag.get("research_version"),
        "candidate_rule": {
            "original_trade_must_exit_in_replayed_INITIAL_SL5": True,
            "first_close_below_original_red_low_required": True,
            "next_close_must_also_remain_below_original_red_low": True,
            "confirmation_timestamp": "SECOND_HELD_CLOSE",
            "contract": "EXACT_MOVING_ATM_PE_AT_CONFIRMATION",
            "entry": "NEXT_MINUTE_OPEN",
            "nearest_strike_fallback": False,
            "nearest_time_fallback": False,
        },
        "source_schema_support": {
            "wide_positioning_schema_supported": True,
            "wide_pe_key": "pe_instrument_key",
            "wide_atm_source_preference": ["moving_atm", "atm", "atm_strike", "strike"],
            "long_positioning_schema_supported": True,
        },
        "exit_policy": {
            "policy_id": POLICY_ID,
            "initial_stop_pct": INITIAL_STOP_PCT,
            "breakeven_trigger_pct": BE_TRIGGER_PCT,
            "trail_activation_pct": TRAIL_TRIGGER_PCT,
            "trail_distance_pct": TRAIL_DISTANCE_PCT,
            "max_hold_minutes": MAX_HOLD_MINUTES,
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
            "next_bar_activation": True,
        },
        "summary": summarize(rows),
        "sep7_reference": next((r for r in rows if r["session_date"] == "2026-09-07"), None),
        "rows": rows,
        "integrity": {
            "candidate_set_predeclared_from_structural_diagnostic": True,
            "single_close_only_case_excluded": True,
            "option_pnl_not_used_to_select_candidates": True,
            "exact_moving_atm_only": True,
            "next_minute_open_only": True,
            "frozen_exit_mechanics_reused": True,
            "no_threshold_sweep": True,
            "no_stop_sweep": True,
            "oos_h_used": False,
            "e_f_g_used": False,
        },
        "governance": {
            "research_only": True,
            "no_v1_change": True,
            "no_reentry_promoted": True,
            "fresh_oos_required_before_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
