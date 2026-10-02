from __future__ import annotations

import argparse, csv, json, math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "OI_FUTURES_VWAP_STANDALONE_V1_5MIN"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}
ROUND_TRIP_COST_PCT_POINTS = 0.5
HORIZONS = (1, 3, 5, 10, 15)


def parse_ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def num(v: Any) -> float | None:
    if v in (None, "", "null", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def validate_block(block: str) -> None:
    if block in FORBIDDEN_BLOCKS:
        raise ValueError(f"{block} is forbidden for development research")
    if block not in ALLOWED_BLOCKS:
        raise ValueError(f"unsupported block: {block}")


def is_five_minute_checkpoint(ts: datetime) -> bool:
    return ts.minute % 5 == 0 and ts.second == 0 and ts.microsecond == 0


def oi_direction(ce_state: str, pe_state: str) -> str:
    ce, pe = (ce_state or "").upper(), (pe_state or "").upper()
    if ce == "LONG_BUILDUP" and pe == "SHORT_BUILDUP":
        return "BULLISH"
    if ce == "SHORT_BUILDUP" and pe == "LONG_BUILDUP":
        return "BEARISH"
    return "NEUTRAL"


def confluence_direction(ce_state: str, pe_state: str, futures_close: float | None, futures_vwap: float | None) -> str:
    if futures_close is None or futures_vwap is None:
        return "NEUTRAL"
    d = oi_direction(ce_state, pe_state)
    if d == "BULLISH" and futures_close > futures_vwap:
        return d
    if d == "BEARISH" and futures_close < futures_vwap:
        return d
    return "NEUTRAL"


def pct_return(entry: float, exit_: float) -> float:
    return (exit_ / entry - 1.0) * 100.0


def exact_atm_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if (num(pick(r, "strike_offset", "offset")) is not None and abs(num(pick(r, "strike_offset", "offset")) or 0.0) < 1e-9)]


def load_futures_index(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for r in load_csv(path):
        ts_raw = pick(r, "timestamp", "provider_timestamp", "datetime", "time")
        if not ts_raw:
            continue
        ts = parse_ts(str(ts_raw))
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        out[(session, ts.isoformat())] = {
            "futures_close": num(pick(r, "futures_close", "close")),
            "futures_vwap": num(pick(r, "futures_vwap", "vwap")),
        }
    return out


def load_ohlc_index(items: list[tuple[str, Path]]) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    idx: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for block, path in items:
        validate_block(block)
        for r in load_csv(path):
            ts_raw = pick(r, "timestamp", "datetime", "time")
            instrument = pick(r, "instrument_key", "instrument")
            if not ts_raw or not instrument:
                continue
            ts = parse_ts(str(ts_raw))
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            idx[(session, str(instrument))][ts.isoformat()] = {k: num(r.get(k)) for k in ("open", "high", "low", "close")}
    return idx


def build_signals(block: str, path: Path, futures_idx: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter]:
    validate_block(block)
    rows = exact_atm_rows(load_csv(path))
    rows.sort(key=lambda r: parse_ts(str(pick(r, "timestamp", "provider_timestamp", "datetime", "time"))))
    prev: dict[str, str] = {}
    issues: Counter = Counter()
    signals = []
    for r in rows:
        ts_raw = pick(r, "timestamp", "provider_timestamp", "datetime", "time")
        if not ts_raw:
            continue
        ts = parse_ts(str(ts_raw))
        if not is_five_minute_checkpoint(ts):
            continue
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        fut = futures_idx.get((session, ts.isoformat()))
        if fut is None:
            issues["MISSING_FUTURES_VWAP_AT_CHECKPOINT"] += 1
            direction = "NEUTRAL"
        else:
            direction = confluence_direction(
                str(pick(r, "ce_5m_state", "ce_state") or ""),
                str(pick(r, "pe_5m_state", "pe_state") or ""),
                fut["futures_close"], fut["futures_vwap"],
            )
        previous = prev.get(session, "NEUTRAL")
        if direction in {"BULLISH", "BEARISH"} and direction != previous:
            side = "CE" if direction == "BULLISH" else "PE"
            key = pick(r, "ce_instrument_key" if side == "CE" else "pe_instrument_key")
            signals.append({
                "block": block, "session_date": session, "signal_timestamp": ts.isoformat(),
                "direction": direction, "option_side": side, "instrument_key": key,
                "strike": num(pick(r, "strike", "moving_atm", "atm", "atm_strike")),
                "moving_atm": num(pick(r, "moving_atm", "atm", "atm_strike", "strike")),
                "ce_state": str(pick(r, "ce_5m_state", "ce_state") or ""),
                "pe_state": str(pick(r, "pe_5m_state", "pe_state") or ""),
                "futures_close": None if fut is None else fut["futures_close"],
                "futures_vwap": None if fut is None else fut["futures_vwap"],
            })
        prev[session] = direction
    return signals, issues


def apply_economics(signal: dict[str, Any], ohlc_idx: dict[tuple[str, str], dict[str, dict[str, Any]]]) -> dict[str, Any]:
    r = dict(signal)
    r.update(entry_available=False, complete_15m_path=False, issue=None)
    key = signal.get("instrument_key")
    if not key:
        r["issue"] = "EXACT_ATM_INSTRUMENT_UNAVAILABLE"
        return r
    series = ohlc_idx.get((signal["session_date"], str(key)), {})
    entry_ts = parse_ts(signal["signal_timestamp"]) + timedelta(minutes=1)
    c = series.get(entry_ts.isoformat())
    if not c or c.get("open") is None:
        r["issue"] = "EXACT_NEXT_MINUTE_OPEN_UNAVAILABLE"
        return r
    entry = float(c["open"])
    if entry <= 0:
        r["issue"] = "INVALID_ENTRY_OPEN"
        return r
    r["entry_available"] = True
    r["entry_timestamp"] = entry_ts.isoformat()
    r["entry_price"] = entry
    gross = {}
    for h in HORIZONS:
        x = series.get((entry_ts + timedelta(minutes=h)).isoformat())
        gross[f"{h}m"] = pct_return(entry, x["close"]) if x and x.get("close") is not None else None
    r["gross_returns_pct"] = gross
    r["net_returns_pct"] = {k: (v - ROUND_TRIP_COST_PCT_POINTS if v is not None else None) for k, v in gross.items()}
    path = [series.get((entry_ts + timedelta(minutes=i)).isoformat()) for i in range(15)]
    path = [x for x in path if x is not None]
    r["complete_15m_path"] = len(path) == 15
    highs = [x["high"] for x in path if x.get("high") is not None]
    lows = [x["low"] for x in path if x.get("low") is not None]
    r["mfe_pct_15m"] = pct_return(entry, max(highs)) if highs else None
    r["mae_pct_15m"] = pct_return(entry, min(lows)) if lows else None
    return r


def metric(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "positive_count": 0, "win_rate_pct": None, "mean_pct": None, "median_pct": None, "sum_pct_points": None, "profit_factor": None}
    pos, neg = [x for x in values if x > 0], [x for x in values if x < 0]
    return {
        "count": len(values), "positive_count": len(pos), "win_rate_pct": len(pos) * 100.0 / len(values),
        "mean_pct": mean(values), "median_pct": median(values), "sum_pct_points": sum(values),
        "profit_factor": (sum(pos) / abs(sum(neg))) if neg else (math.inf if pos else None),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if r.get("entry_available")]
    out = {"trade_count": len(rows), "direction_counts": dict(Counter(r["direction"] for r in rows))}
    for h in HORIZONS:
        vals = [r["net_returns_pct"][f"{h}m"] for r in rows if r.get("net_returns_pct", {}).get(f"{h}m") is not None]
        out[f"net_{h}m"] = metric([float(x) for x in vals])
    return out


def named(v: str) -> tuple[str, Path]:
    block, path = v.split("|", 1)
    validate_block(block)
    return block, Path(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positioning", action="append", required=True)
    ap.add_argument("--option-ohlc", action="append", required=True)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    pos = [named(x) for x in args.positioning]
    ohlc_idx = load_ohlc_index([named(x) for x in args.option_ohlc])
    fut = load_futures_index(Path(args.futures_vwap))
    all_rows, issues, by_block = [], Counter(), {}
    for block, path in pos:
        sig, iss = build_signals(block, path, fut)
        issues.update(iss)
        trades = [apply_economics(x, ohlc_idx) for x in sig]
        all_rows.extend(trades)
        by_block[block] = summarize(trades)
    doc = {
        "status": "AVAILABLE", "research_version": RESEARCH_VERSION, "research_status": "DEVELOPMENT_ONLY",
        "forbidden_blocks": sorted(FORBIDDEN_BLOCKS),
        "signal_issue_counts": dict(issues),
        "summary": {"transition_signal_count": len(all_rows), "complete_trade_count": sum(bool(r.get("entry_available")) for r in all_rows), "overall": summarize(all_rows), "by_block": by_block},
        "trades": all_rows,
    }
    Path(args.output).write_text(json.dumps(doc, indent=2, allow_nan=False, default=str), encoding="utf-8")
    print(json.dumps(doc["summary"], indent=2, default=str))


if __name__ == "__main__":
    main()
