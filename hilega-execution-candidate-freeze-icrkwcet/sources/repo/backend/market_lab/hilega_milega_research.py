"""Fixed-rule NIFTY research in index points, not executable futures/option P&L."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from dotenv import dotenv_values

from .gateways import UpstoxGateway

IST = ZoneInfo("Asia/Kolkata")
RULES = ("ema_wma", "ema_wma_rsi50", "rsi50")


def indicators(closes):
    """Wilder RSI(9), first-value-seeded EMA(3), and linear WMA(21)."""
    result = []
    gains, losses, history = [], [], []
    avg_gain = avg_loss = ema = None
    for i, close in enumerate(closes):
        if i == 0:
            result.append(None)
            continue
        delta = close - closes[i - 1]
        gain, loss = max(delta, 0), max(-delta, 0)
        if i <= 9:
            gains.append(gain)
            losses.append(loss)
            if i < 9:
                result.append(None)
                continue
            avg_gain, avg_loss = sum(gains) / 9, sum(losses) / 9
        else:
            avg_gain = (avg_gain * 8 + gain) / 9
            avg_loss = (avg_loss * 8 + loss) / 9
        rsi = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        ema = rsi if ema is None else 0.5 * rsi + 0.5 * ema
        history.append(rsi)
        wma = sum((j + 1) * x for j, x in enumerate(history[-21:])) / 231 if len(history) >= 21 else None
        result.append((rsi, ema, wma))
    return result


def crossing(previous, current):
    return 1 if previous <= 0 < current else -1 if previous >= 0 > current else 0


def signals(previous, current, rule):
    if previous is None or current is None or previous[2] is None or current[2] is None:
        return 0, 0
    raw = crossing(previous[0] - 50, current[0] - 50) if rule == "rsi50" else crossing(
        previous[1] - previous[2], current[1] - current[2]
    )
    entry = raw
    if rule == "ema_wma_rsi50" and raw * (current[0] - 50) <= 0:
        entry = 0
    return raw, entry


def simulate(bars, values, rule, eligible_dates):
    trades = []
    position = 0
    entry_bar = None
    for i in range(1, len(bars)):
        bar, previous_bar = bars[i], bars[i - 1]
        if bar["timestamp"].date() not in eligible_dates:
            continue
        if bar["timestamp"].date() != previous_bar["timestamp"].date():
            if position:
                raise ValueError("Position unexpectedly crossed a session boundary")
            continue
        if bar["timestamp"] - previous_bar["timestamp"] != timedelta(minutes=5):
            raise ValueError("Non-contiguous execution bars")
        raw, entry = signals(values[i - 2] if i >= 2 else None, values[i - 1], rule)
        square_off = bar["timestamp"].time() >= time(15, 20)
        if position and (square_off or raw == -position):
            trades.append({
                "rule": rule, "entry": entry_bar["timestamp"].isoformat(),
                "exit": bar["timestamp"].isoformat(), "side": "long" if position == 1 else "short",
                "entry_price": entry_bar["open"], "exit_price": bar["open"],
                "gross_points": position * (bar["open"] - entry_bar["open"]),
                "reason": "15:20_exit" if square_off else "opposite_cross",
            })
            position = 0
        if not square_off and entry and not position:
            position, entry_bar = entry, bar
    if position:
        raise ValueError("Unclosed final position")
    return trades


def metrics(trades, cost):
    returns = [t["gross_points"] - cost for t in trades]
    equity = peak = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gains = sum(max(x, 0) for x in returns)
    losses = sum(max(-x, 0) for x in returns)
    return {
        "trades": len(returns), "net_points": round(sum(returns), 2),
        "win_percent": round(100 * sum(x > 0 for x in returns) / len(returns), 2) if returns else None,
        "profit_factor": round(gains / losses, 3) if losses else None,
        "closed_trade_max_drawdown_points": round(drawdown, 2),
        "average_points": round(sum(returns) / len(returns), 3) if returns else None,
    }


def load_bars(folder, start, end):
    grouped = defaultdict(list)
    seen = set()
    for path in sorted(folder.glob("candles-*.json")):
        for row in json.loads(path.read_text())["data"]["candles"]:
            ts = datetime.fromisoformat(row[0]).astimezone(IST)
            if not start <= ts.date() <= end:
                continue
            if ts in seen:
                raise ValueError(f"Duplicate candle: {ts}")
            seen.add(ts)
            prices = [float(x) for x in row[1:5]]
            if not all(math.isfinite(x) and x > 0 for x in prices):
                raise ValueError(f"Invalid price: {ts}")
            op, hi, lo, cl = prices
            if not lo <= min(op, cl) <= max(op, cl) <= hi:
                raise ValueError(f"Invalid OHLC: {ts}")
            grouped[ts.date()].append(dict(timestamp=ts, open=op, high=hi, low=lo, close=cl))
    bars, excluded = [], []
    for day, rows in sorted(grouped.items()):
        rows.sort(key=lambda x: x["timestamp"])
        expected = [datetime.combine(day, time(9, 15), IST) + timedelta(minutes=5 * i) for i in range(75)]
        if [r["timestamp"] for r in rows] != expected:
            excluded.append({"date": str(day), "rows": len(rows), "reason": "not a complete regular session"})
            continue
        bars.extend(rows)
    return bars, excluded


def fetch(folder, start, end):
    token = dotenv_values(Path(__file__).resolve().parents[2] / ".env").get("UPSTOX_ACCESS_TOKEN", "")
    gateway = UpstoxGateway(token)
    try:
        current = start
        while current <= end:
            last = min(current + timedelta(days=27), end)
            path = folder / f"candles-{current}-{last}.json"
            if not path.exists():
                body = gateway._get(
                    f"/v3/historical-candle/{quote('NSE_INDEX|Nifty 50', safe='')}/minutes/5/{last}/{current}", {}
                )
                path.write_text(json.dumps(body), encoding="utf-8")
            print(f"Cached {current} to {last}", flush=True)
            current = last + timedelta(days=1)
    finally:
        gateway.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 9, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 17))
    parser.add_argument("--output", type=Path, default=Path("data/hilega-milega-research"))
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("end must not precede start")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        fetch(args.output, args.start, args.end)
    bars, excluded = load_bars(args.output, args.start, args.end)
    days = sorted({b["timestamp"].date() for b in bars})
    if len(days) < 60:
        raise ValueError(f"Need at least 60 complete sessions; found {len(days)}")
    # Five sessions warm the recursive indicators before any scored trades.
    scored_days = days[5:]
    cut = int(len(scored_days) * 0.7)
    segments = {"train": set(scored_days[:cut]), "holdout": set(scored_days[cut:])}
    values = indicators([b["close"] for b in bars])
    all_trades, results = [], {}
    for segment, selected_days in segments.items():
        results[segment] = {}
        for rule in RULES:
            trades = simulate(bars, values, rule, selected_days)
            all_trades.extend(dict(t, segment=segment) for t in trades)
            monthly = defaultdict(list)
            for trade in trades:
                monthly[trade["entry"][:7]].append(trade)
            results[segment][rule] = {
                "cost_sensitivity": {str(cost): metrics(trades, cost) for cost in (0, 2, 5, 10)},
                "sides_at_2_points": {side: metrics([t for t in trades if t["side"] == side], 2)
                                      for side in ("long", "short")},
                "months_at_2_points": {month: metrics(ts, 2) for month, ts in sorted(monthly.items())},
            }
    winner = max(RULES, key=lambda rule: results["train"][rule]["cost_sensitivity"]["2"]["net_points"])
    report = {
        "instrument": "NSE_INDEX|Nifty 50", "timeframe_minutes": 5,
        "source": "Upstox historical candle API v3", "complete_sessions": len(days),
        "bars": len(bars), "excluded_sessions": excluded, "warmup_sessions": 5,
        "segments": {name: {"start": str(min(ds)), "end": str(max(ds)), "sessions": len(ds)}
                     for name, ds in segments.items()},
        "assumptions": [
            "Original RSI(9), EMA(3) of RSI, WMA(21) of RSI; close source.",
            "Closed-bar cross, next 5-minute open fill; fresh cross required for entry.",
            "Both long and short; one position; no pyramiding, protective stop or profit target.",
            "Opposite raw crossover exits even if RSI entry filter blocks reversal.",
            "No overnight positions; scheduled exit at 15:20 IST open; earliest entry 09:20.",
            "Indicators carry across complete sessions; first five sessions are warmup.",
            "Fixed 70/30 chronological session split; selection uses train net points at 2 points cost.",
            "Costs are hypothetical round-trip index points, not actual fees or futures/option returns.",
            "Drawdown uses closed trades only; intratrade drawdown can be larger.",
            "Missing whole sessions cannot be detected without an exchange calendar.",
            "Holdout is unused by this script for selection, not guaranteed untouched by prior research.",
        ],
        "selected_on_train": winner, "results": results,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if all_trades:
        with (args.output / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_trades[0]))
            writer.writeheader()
            writer.writerows(all_trades)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
