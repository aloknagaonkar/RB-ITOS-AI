from __future__ import annotations

import argparse, csv, json, math
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

MODEL = "STRUCTURE_PRICE_LAG_EXACT_OPTION_REPLAY_V1"
HORIZONS = (1, 3, 5, 10, 15, 30, 60)
UNDERLYING_TARGETS = (20, 30, 40, 50, 75, 100)
ROUND_TRIP_COST_PCT_POINTS = 0.5


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _parse_ts(s):
    return datetime.fromisoformat(str(s))


def _split_spec(spec):
    if "|" not in spec:
        raise ValueError(f"Expected BLOCK|path, got {spec}")
    b, p = spec.split("|", 1)
    return b, Path(p)


def load_csvs(specs):
    out = {}
    for spec in specs:
        block, path = _split_spec(spec)
        with path.open(newline="") as f:
            out[block] = list(csv.DictReader(f))
    return out


def block_dates(manifest_specs):
    mapping = {}
    for spec in manifest_specs:
        block, path = _split_spec(spec)
        obj = json.loads(path.read_text())
        sessions = obj.get("sessions") or obj.get("data") or []
        for x in sessions:
            d = str(x.get("session_date") or x.get("date") or "")
            if d:
                mapping[d] = block
    return mapping


def _first(row, *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _norm_side(v):
    s = str(v or "").upper()
    if s in {"CE", "CALL", "C"}:
        return "CE"
    if s in {"PE", "PUT", "P"}:
        return "PE"
    return None


def _find_exact_instrument(positioning_rows, session_date, confirmation_ts, side):
    """
    Resolve the exact moving-ATM instrument from positioning evidence.

    Wide schema preferred:
      timestamp/session_date, moving_atm, strike, strike_offset,
      ce_instrument_key/pe_instrument_key.

    Long schema fallback:
      timestamp/session_date, strike, option_type/side, instrument_key,
      moving_atm/atm/atm_strike.
    """
    ts = str(confirmation_ts)
    exact = [
        r for r in positioning_rows
        if str(_first(r, "session_date", "date") or session_date) == session_date
        and str(_first(r, "timestamp", "ts", "checkpoint_timestamp") or "") == ts
    ]
    if not exact:
        return None, None, "NO_EXACT_POSITIONING_TIMESTAMP"

    # Wide schema.
    key_field = "ce_instrument_key" if side == "CE" else "pe_instrument_key"
    wide = []
    for r in exact:
        key = r.get(key_field)
        if not key:
            continue
        off = _num(r.get("strike_offset"))
        strike = _num(_first(r, "strike", "strike_price"))
        atm = _num(_first(r, "moving_atm", "atm", "atm_strike"))
        is_atm = (off == 0) if off is not None else (
            strike is not None and atm is not None and strike == atm
        )
        if is_atm:
            wide.append((str(key), strike if strike is not None else atm))
    if len({x[0] for x in wide}) == 1 and wide:
        return wide[0][0], wide[0][1], None
    if len({x[0] for x in wide}) > 1:
        return None, None, "AMBIGUOUS_EXACT_ATM_INSTRUMENT"

    # Long schema.
    candidates = []
    for r in exact:
        rside = _norm_side(_first(r, "option_type", "side", "instrument_type"))
        if rside != side:
            continue
        key = _first(r, "instrument_key", "option_instrument_key")
        strike = _num(_first(r, "strike", "strike_price"))
        atm = _num(_first(r, "moving_atm", "atm", "atm_strike"))
        off = _num(r.get("strike_offset"))
        is_atm = (off == 0) if off is not None else (
            strike is not None and atm is not None and strike == atm
        )
        if key and is_atm:
            candidates.append((str(key), strike if strike is not None else atm))

    uniq = {}
    for key, strike in candidates:
        uniq[key] = strike
    if len(uniq) == 1:
        key, strike = next(iter(uniq.items()))
        return key, strike, None
    if len(uniq) > 1:
        return None, None, "AMBIGUOUS_EXACT_ATM_INSTRUMENT"
    return None, None, "NO_EXACT_ATM_INSTRUMENT"


def _index_option_rows(rows):
    idx = defaultdict(dict)
    for r in rows:
        key = _first(r, "instrument_key", "option_instrument_key")
        ts = _first(r, "timestamp", "ts")
        if not key or not ts:
            continue
        idx[str(key)][str(ts)] = r
    return idx


def _price(row, field):
    return _num(row.get(field)) if row else None


def _gross_pct(entry, exit_price):
    if entry is None or exit_price is None or entry <= 0:
        return None
    return (exit_price / entry - 1.0) * 100.0


def _net_pct(entry, exit_price):
    g = _gross_pct(entry, exit_price)
    return None if g is None else g - ROUND_TRIP_COST_PCT_POINTS


def _path_rows(idx, key, start_ts, minutes):
    start = _parse_ts(start_ts)
    out = []
    for m in range(minutes + 1):
        ts = (start + timedelta(minutes=m)).isoformat()
        r = idx.get(key, {}).get(ts)
        if r:
            out.append(r)
    return out


def build_replay(events_path, date_to_block, positioning_by_block, ohlc_by_block):
    with Path(events_path).open(newline="") as f:
        events = list(csv.DictReader(f))

    ohlc_idx = {b: _index_option_rows(rows) for b, rows in ohlc_by_block.items()}
    trades = []
    issues = Counter()

    for e in events:
        d = e["session_date"]
        block = date_to_block.get(d)
        if not block:
            issues["NO_BLOCK_FOR_DATE"] += 1
            continue
        if block not in positioning_by_block:
            issues["NO_POSITIONING_BLOCK"] += 1
            continue
        if block not in ohlc_idx:
            issues["NO_OHLC_BLOCK"] += 1
            continue

        direction = e["direction"].upper()
        side = "CE" if direction == "BULLISH" else "PE"
        confirmation_ts = e["confirmation_timestamp_candle2"]

        key, strike, issue = _find_exact_instrument(
            positioning_by_block[block], d, confirmation_ts, side
        )
        if issue:
            issues[issue] += 1
            continue

        entry_ts = (_parse_ts(confirmation_ts) + timedelta(minutes=1)).isoformat()
        entry_row = ohlc_idx[block].get(key, {}).get(entry_ts)
        entry = _price(entry_row, "open")
        if entry is None:
            issues["NO_EXACT_NEXT_MINUTE_OPEN"] += 1
            continue

        t = {
            "event_id": int(e["event_id"]),
            "session_date": d,
            "block": block,
            "direction": direction,
            "price_lag_class": e["price_lag_class"],
            "confirmation_timestamp": confirmation_ts,
            "confirmation_spot": _num(e.get("confirmation_spot_c2")),
            "option_side": side,
            "strike": strike,
            "instrument_key": key,
            "entry_timestamp": entry_ts,
            "entry_open": entry,
        }

        # Fixed-horizon closes, no nearest-time fallback.
        for m in HORIZONS:
            ts = (_parse_ts(entry_ts) + timedelta(minutes=m)).isoformat()
            r = ohlc_idx[block].get(key, {}).get(ts)
            close = _price(r, "close")
            t[f"option_close_plus_{m}m"] = close
            t[f"gross_return_plus_{m}m_pct"] = _gross_pct(entry, close)
            t[f"net_return_plus_{m}m_pct"] = _net_pct(entry, close)

        # Premium MFE/MAE over 15/30/60m based on exact minute high/low.
        for m in (15, 30, 60):
            path = _path_rows(ohlc_idx[block], key, entry_ts, m)
            highs = [_price(r, "high") for r in path]
            lows = [_price(r, "low") for r in path]
            highs = [x for x in highs if x is not None]
            lows = [x for x in lows if x is not None]
            max_high = max(highs) if highs else None
            min_low = min(lows) if lows else None
            t[f"option_mfe_plus_{m}m_pct"] = _gross_pct(entry, max_high)
            t[f"option_mae_plus_{m}m_pct"] = _gross_pct(entry, min_low)

        # Direct bridge: premium at the exact minute NIFTY first hit each target.
        for target in UNDERLYING_TARGETS:
            hit = str(e.get(f"hit_{target}pt", "")).lower() == "true"
            hit_ts = e.get(f"timestamp_hit_{target}pt") if hit else None
            t[f"nifty_hit_{target}pt"] = hit
            t[f"nifty_time_to_{target}pt_minutes"] = _num(
                e.get(f"time_to_{target}pt_minutes")
            )
            t[f"nifty_{target}pt_timestamp"] = hit_ts or None
            if hit_ts:
                r = ohlc_idx[block].get(key, {}).get(hit_ts)
                option_close = _price(r, "close")
            else:
                option_close = None
            t[f"option_close_at_nifty_{target}pt"] = option_close
            t[f"option_points_at_nifty_{target}pt"] = (
                None if option_close is None else option_close - entry
            )
            t[f"option_gross_pct_at_nifty_{target}pt"] = _gross_pct(entry, option_close)

        trades.append(t)

    return trades, dict(issues), len(events)


def _vals(rows, key):
    out = []
    for r in rows:
        v = _num(r.get(key))
        if v is not None:
            out.append(v)
    return out


def _avg(rows, key):
    x = _vals(rows, key)
    return None if not x else mean(x)


def _med(rows, key):
    x = _vals(rows, key)
    return None if not x else median(x)


def _positive_rate(rows, key):
    x = _vals(rows, key)
    return None if not x else sum(v > 0 for v in x) / len(x)


def summarize(rows):
    out = {"trades": len(rows)}
    for m in HORIZONS:
        k = f"net_return_plus_{m}m_pct"
        out[f"net_{m}m_available"] = len(_vals(rows, k))
        out[f"net_{m}m_positive_rate"] = _positive_rate(rows, k)
        out[f"net_{m}m_mean_pct"] = _avg(rows, k)
        out[f"net_{m}m_median_pct"] = _med(rows, k)
    for m in (15, 30, 60):
        out[f"median_option_mfe_{m}m_pct"] = _med(rows, f"option_mfe_plus_{m}m_pct")
        out[f"median_option_mae_{m}m_pct"] = _med(rows, f"option_mae_plus_{m}m_pct")
    for target in UNDERLYING_TARGETS:
        hit_rows = [r for r in rows if r.get(f"nifty_hit_{target}pt")]
        out[f"nifty_{target}pt_hit_trades"] = len(hit_rows)
        out[f"option_at_nifty_{target}pt_available"] = len(
            _vals(hit_rows, f"option_points_at_nifty_{target}pt")
        )
        out[f"median_option_points_at_nifty_{target}pt"] = _med(
            hit_rows, f"option_points_at_nifty_{target}pt"
        )
        out[f"mean_option_points_at_nifty_{target}pt"] = _avg(
            hit_rows, f"option_points_at_nifty_{target}pt"
        )
        out[f"median_option_gross_pct_at_nifty_{target}pt"] = _med(
            hit_rows, f"option_gross_pct_at_nifty_{target}pt"
        )
    return out


def build_report(trades, issues, candidate_count):
    lag = [r for r in trades if r["price_lag_class"] == "SPOT_LAG"]
    moved = [r for r in trades if r["price_lag_class"] == "SPOT_ALREADY_MOVED"]
    bull = [r for r in trades if r["direction"] == "BULLISH"]
    bear = [r for r in trades if r["direction"] == "BEARISH"]
    return {
        "status": "PASS",
        "model": MODEL,
        "role": "EXACT_OPTION_ECONOMICS_DESCRIPTIVE_ONLY",
        "strategy_logic_changed": False,
        "threshold_optimization": False,
        "contract_rule": "EXACT_MOVING_ATM_AT_CANDLE2_CONFIRMATION_NO_NEAREST_STRIKE_FALLBACK",
        "entry_rule": "EXACT_NEXT_MINUTE_OPEN_NO_NEAREST_TIME_FALLBACK",
        "side_rule": "BULLISH->CE, BEARISH->PE",
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "candidate_count": candidate_count,
        "exact_trade_count": len(trades),
        "issue_counts": issues,
        "research_questions": [
            "Does the validated structural confirmation translate into exact CE/PE premium economics?",
            "Does SPOT_LAG retain an advantage over SPOT_ALREADY_MOVED in option returns?",
            "When NIFTY first reaches +20/+30/+40/+50/+75/+100 target points, how many option premium points were actually captured?",
        ],
        "important_notes": [
            "No NIFTY-point-to-option-point assumption is used.",
            "Premium bridge is measured from exact historical option candles.",
            "Point targets remain descriptive; they are not entry/exit thresholds.",
            "No nearest strike or nearest timestamp substitution is allowed.",
        ],
        "all": summarize(trades),
        "by_price_lag": {
            "SPOT_LAG": summarize(lag),
            "SPOT_ALREADY_MOVED": summarize(moved),
        },
        "by_direction": {
            "BULLISH": {
                "all": summarize(bull),
                "SPOT_LAG": summarize([r for r in bull if r["price_lag_class"] == "SPOT_LAG"]),
                "SPOT_ALREADY_MOVED": summarize([r for r in bull if r["price_lag_class"] == "SPOT_ALREADY_MOVED"]),
            },
            "BEARISH": {
                "all": summarize(bear),
                "SPOT_LAG": summarize([r for r in bear if r["price_lag_class"] == "SPOT_LAG"]),
                "SPOT_ALREADY_MOVED": summarize([r for r in bear if r["price_lag_class"] == "SPOT_ALREADY_MOVED"]),
            },
        },
        "trades": trades,
    }


def write_csv(rows, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("")
        return
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--manifest", action="append", required=True)
    ap.add_argument("--positioning", action="append", required=True)
    ap.add_argument("--option-ohlc", action="append", required=True)
    ap.add_argument("--trades-csv", required=True)
    ap.add_argument("--summary-json", required=True)
    a = ap.parse_args(argv)

    dates = block_dates(a.manifest)
    positioning = load_csvs(a.positioning)
    ohlc = load_csvs(a.option_ohlc)
    trades, issues, candidate_count = build_replay(a.events, dates, positioning, ohlc)
    report = build_report(trades, issues, candidate_count)

    write_csv(trades, a.trades_csv)
    out = Path(a.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
