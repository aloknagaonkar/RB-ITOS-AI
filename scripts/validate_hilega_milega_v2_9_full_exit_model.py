#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, os, sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UNDERLYING = "NSE_INDEX|Nifty 50"

@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    oi: int | None = None
    rsi: float | None = None
    ema: float | None = None
    wma: float | None = None

def fetch_1m(token: str, sd: date) -> list[Bar]:
    repo_root = Path(__file__).resolve().parents[1]
    backend = repo_root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from market_lab.gateways import UpstoxGateway

    gateway = UpstoxGateway(token)
    candles = gateway.historical_candles(UNDERLYING, sd)
    out = []
    for c in candles:
        ts = c.timestamp.astimezone(IST)
        if ts.date() != sd:
            continue
        out.append(Bar(
            ts=ts,
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
            volume=None if c.volume is None else int(c.volume),
            oi=None if c.open_interest is None else int(c.open_interest),
        ))
    return sorted(out, key=lambda b: b.ts)

def to5(rows: list[Bar]) -> list[Bar]:
    buckets = {}
    for b in rows:
        t = b.ts.astimezone(IST)
        if (t.hour, t.minute) < (9, 15) or (t.hour, t.minute) > (15, 29):
            continue
        key = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
        buckets.setdefault(key, []).append(b)
    out = []
    for ts, g in sorted(buckets.items()):
        g = sorted(g, key=lambda b: b.ts)
        if len(g) != 5:
            continue
        expected = [ts + timedelta(minutes=i) for i in range(5)]
        actual = [x.ts.replace(second=0, microsecond=0) for x in g]
        if actual != expected:
            continue
        out.append(Bar(
            ts=ts,
            open=g[0].open,
            high=max(x.high for x in g),
            low=min(x.low for x in g),
            close=g[-1].close,
            volume=sum(x.volume or 0 for x in g),
            oi=g[-1].oi,
        ))
    return out

def rsi_wilder(closes: list[float], n: int = 9):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    ag = sum(gains[1:n+1]) / n
    al = sum(losses[1:n+1]) / n
    def calc(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)
    out[n] = calc(ag, al)
    for i in range(n + 1, len(closes)):
        ag = ((n - 1) * ag + gains[i]) / n
        al = ((n - 1) * al + losses[i]) / n
        out[i] = calc(ag, al)
    return out

def ema(values, n=3):
    out = [None] * len(values)
    alpha = 2.0 / (n + 1)
    s = None
    for i, x in enumerate(values):
        if x is None:
            continue
        s = x if s is None else alpha * x + (1 - alpha) * s
        out[i] = s
    return out

def wma(values, n=21):
    out = [None] * len(values)
    den = n * (n + 1) / 2
    for i in range(n - 1, len(values)):
        window = values[i - n + 1:i + 1]
        if any(x is None for x in window):
            continue
        out[i] = sum((j + 1) * float(x) for j, x in enumerate(window)) / den
    return out

def cross_up(a0, b0, a1, b1):
    return None not in (a0, b0, a1, b1) and a0 <= b0 and a1 > b1

def cross_down(a0, b0, a1, b1):
    return None not in (a0, b0, a1, b1) and a0 >= b0 and a1 < b1

def full_alignment(b: Bar):
    return (
        None not in (b.rsi, b.ema, b.wma)
        and b.rsi > 50 and b.ema > 50 and b.wma > 50
        and b.rsi > b.ema > b.wma
    )

def f2(x):
    return "" if x is None else f"{x:.2f}"

def replay(bs: list[Bar]):
    events = []
    regimes = []

    active = False
    weakening = False
    armed = False
    armed_time = ""
    reg = None

    opening_candidate = False
    opening_holding = False

    for i, b in enumerate(bs):
        if None in (b.rsi, b.ema, b.wma):
            continue

        prev = bs[i - 1] if i else None
        t = b.ts.strftime("%H:%M")

        rsi_up = bool(prev and prev.rsi is not None and b.rsi > prev.rsi)
        ema_up = bool(prev and prev.ema is not None and b.ema > prev.ema)
        rsi_cross_ema = bool(prev and cross_up(prev.rsi, prev.ema, b.rsi, b.ema))
        rsi_cross_down_wma = bool(prev and cross_down(prev.rsi, prev.wma, b.rsi, b.wma))

        # OPENING PATH
        if t == "09:15" and full_alignment(b):
            opening_candidate = True
            events.append((t, "OPENING_ALIGNMENT"))

        elif t == "09:20" and opening_candidate:
            if b.rsi > b.wma:
                opening_holding = True
                events.append((t, "OPENING_HOLDING"))
            else:
                opening_candidate = False
                opening_holding = False
                events.append((t, "OPENING_REJECTED_0920"))

        elif t == "09:25" and opening_candidate and opening_holding:
            if b.rsi > b.wma and not active:
                active = True
                weakening = False
                reg = {
                    "source": "OPENING_PATH",
                    "armed_time": "",
                    "si": i,
                    "start_time": t,
                    "start_close": b.close,
                    "weakening_count": 0,
                    "continuation_count": 0,
                }
                events.append((t, "OPENING_BULLISH_CONFIRMED"))
            else:
                events.append((t, "OPENING_REJECTED_0925"))
            opening_candidate = False
            opening_holding = False

        # ACTIVE REGIME / INVALIDATION
        if active:
            if weakening:
                if b.rsi < b.wma:
                    reg.update(
                        end_time=t,
                        end_close=b.close,
                        points_to_end=b.close - reg["start_close"],
                        duration_minutes=int((b.ts - bs[reg["si"]].ts).total_seconds() / 60),
                    )
                    window = bs[reg["si"]:i + 1]
                    reg["mfe_points"] = max(x.high for x in window) - reg["start_close"]
                    reg["mae_points"] = min(x.low for x in window) - reg["start_close"]

                    target = reg["start_close"] + 20.0
                    reg["target_20_price"] = target
                    reg["target_20_hit"] = False
                    reg["target_20_hit_time"] = ""
                    reg["target_20_minutes"] = None
                    reg["nextbar_mfe_points"] = None
                    reg["nextbar_mae_points"] = None
                    post = bs[reg["si"] + 1:i + 1]

                    # Exact target-vs-stop first-touch research.
                    # We only use bars AFTER the bullish signal candle.
                    # If target and stop are both touched in the same 5m candle,
                    # mark AMBIGUOUS rather than assuming an intrabar order.
                    for stop_pts in (10, 15, 20, 25, 30, 40, 50):
                        stop_price = reg["start_close"] - float(stop_pts)
                        key = f"sl_{stop_pts}"
                        reg[f"{key}_price"] = stop_price
                        reg[f"{key}_outcome"] = "NO_EXIT"
                        reg[f"{key}_exit_time"] = ""
                        reg[f"{key}_points"] = None

                        for x in post:
                            hit_target = x.high >= target
                            hit_stop = x.low <= stop_price

                            if hit_target and hit_stop:
                                reg[f"{key}_outcome"] = "AMBIGUOUS_SAME_CANDLE"
                                reg[f"{key}_exit_time"] = x.ts.strftime("%H:%M")
                                reg[f"{key}_points"] = None
                                break
                            if hit_target:
                                reg[f"{key}_outcome"] = "TARGET"
                                reg[f"{key}_exit_time"] = x.ts.strftime("%H:%M")
                                reg[f"{key}_points"] = 20.0
                                break
                            if hit_stop:
                                reg[f"{key}_outcome"] = "STOP"
                                reg[f"{key}_exit_time"] = x.ts.strftime("%H:%M")
                                reg[f"{key}_points"] = -float(stop_pts)
                                break

                    if post:
                        reg["nextbar_mfe_points"] = max(x.high for x in post) - reg["start_close"]
                        reg["nextbar_mae_points"] = min(x.low for x in post) - reg["start_close"]
                        pre_target_bars = []
                        for x in post:
                            pre_target_bars.append(x)
                            if x.high >= target:
                                reg["target_20_hit"] = True
                                reg["target_20_hit_time"] = x.ts.strftime("%H:%M")
                                reg["target_20_minutes"] = int((x.ts - bs[reg["si"]].ts).total_seconds() / 60)
                                reg["pre_target_mae_points"] = min(y.low for y in pre_target_bars) - reg["start_close"]
                                reg["pre_target_mfe_points"] = max(y.high for y in pre_target_bars) - reg["start_close"]
                                break
                    # Partial-profit research after a confirmed +20 hit.
                    # Conservative sequencing: runner management begins from the NEXT 5m candle
                    # after the candle that first touched +20.
                    if reg.get("target_20_hit"):
                        hit_idx = None
                        for j in range(reg["si"] + 1, i + 1):
                            if bs[j].ts.strftime("%H:%M") == reg.get("target_20_hit_time"):
                                hit_idx = j
                                break

                        if hit_idx is not None:
                            runner_bars = bs[hit_idx + 1:i + 1]
                            for runner_target in (30, 40, 50):
                                prefix = f"runner_{runner_target}"
                                reg[f"{prefix}_outcome"] = "END_EXIT"
                                reg[f"{prefix}_exit_time"] = reg.get("end_time", "")
                                reg[f"{prefix}_runner_points"] = reg.get("points_to_end")
                                for x in runner_bars:
                                    hit_runner = x.high >= reg["start_close"] + float(runner_target)
                                    hit_be = x.low <= reg["start_close"]
                                    if hit_runner and hit_be:
                                        reg[f"{prefix}_outcome"] = "AMBIGUOUS_SAME_CANDLE"
                                        reg[f"{prefix}_exit_time"] = x.ts.strftime("%H:%M")
                                        reg[f"{prefix}_runner_points"] = None
                                        break
                                    if hit_runner:
                                        reg[f"{prefix}_outcome"] = "RUNNER_TARGET"
                                        reg[f"{prefix}_exit_time"] = x.ts.strftime("%H:%M")
                                        reg[f"{prefix}_runner_points"] = float(runner_target)
                                        break
                                    if hit_be:
                                        reg[f"{prefix}_outcome"] = "BREAK_EVEN"
                                        reg[f"{prefix}_exit_time"] = x.ts.strftime("%H:%M")
                                        reg[f"{prefix}_runner_points"] = 0.0
                                        break

                                rp = reg.get(f"{prefix}_runner_points")
                                reg[f"{prefix}_combined_50_50_points"] = (
                                    10.0 + 0.5 * rp if rp is not None else None
                                )

                    regimes.append(reg)
                    events.append((t, "BULLISH_END_CONFIRMED"))
                    active = False
                    weakening = False
                    reg = None
                    continue
                else:
                    weakening = False
                    reg["continuation_count"] += 1
                    events.append((t, "WEAKENING_RECOVERY_CONTINUATION"))

            if active and not weakening and rsi_cross_down_wma:
                weakening = True
                reg["weakening_count"] += 1
                events.append((t, "WEAKENING"))
            continue

        # NORMAL PATH 1 ONLY
        if rsi_cross_ema:
            armed = True
            armed_time = t
            events.append((t, "PATH1_ARMED"))

        path1_bullish = (
            armed
            and b.rsi > b.wma
            and b.ema > b.wma
            and rsi_up
            and ema_up
        )

        if path1_bullish:
            active = True
            weakening = False
            reg = {
                "source": "PATH_1_RSI_EMA_ARMED",
                "armed_time": armed_time,
                "si": i,
                "start_time": t,
                "start_close": b.close,
                "weakening_count": 0,
                "continuation_count": 0,
            }
            events.append((t, "BULLISH_START:PATH_1_RSI_EMA_ARMED"))
            armed = False
            armed_time = ""

    if active and reg:
        window = bs[reg["si"]:]
        reg.update(
            end_time="",
            end_close=None,
            points_to_end=None,
            duration_minutes=int((bs[-1].ts - bs[reg["si"]].ts).total_seconds() / 60),
            mfe_points=max(x.high for x in window) - reg["start_close"],
            mae_points=min(x.low for x in window) - reg["start_close"],
            session_end_time=bs[-1].ts.strftime("%H:%M"),
            session_end_close=bs[-1].close,
            session_end_points=bs[-1].close - reg["start_close"],
        )
        target = reg["start_close"] + 20.0
        reg["target_20_price"] = target
        reg["target_20_hit"] = False
        reg["target_20_hit_time"] = ""
        reg["target_20_minutes"] = None
        reg["nextbar_mfe_points"] = None
        reg["nextbar_mae_points"] = None
        post = bs[reg["si"] + 1:]

        for stop_pts in (10, 15, 20, 25, 30, 40, 50):
            stop_price = reg["start_close"] - float(stop_pts)
            key = f"sl_{stop_pts}"
            reg[f"{key}_price"] = stop_price
            reg[f"{key}_outcome"] = "NO_EXIT"
            reg[f"{key}_exit_time"] = ""
            reg[f"{key}_points"] = None

            for x in post:
                hit_target = x.high >= target
                hit_stop = x.low <= stop_price

                if hit_target and hit_stop:
                    reg[f"{key}_outcome"] = "AMBIGUOUS_SAME_CANDLE"
                    reg[f"{key}_exit_time"] = x.ts.strftime("%H:%M")
                    reg[f"{key}_points"] = None
                    break
                if hit_target:
                    reg[f"{key}_outcome"] = "TARGET"
                    reg[f"{key}_exit_time"] = x.ts.strftime("%H:%M")
                    reg[f"{key}_points"] = 20.0
                    break
                if hit_stop:
                    reg[f"{key}_outcome"] = "STOP"
                    reg[f"{key}_exit_time"] = x.ts.strftime("%H:%M")
                    reg[f"{key}_points"] = -float(stop_pts)
                    break

        if post:
            reg["nextbar_mfe_points"] = max(x.high for x in post) - reg["start_close"]
            reg["nextbar_mae_points"] = min(x.low for x in post) - reg["start_close"]
            pre_target_bars = []
            for x in post:
                pre_target_bars.append(x)
                if x.high >= target:
                    reg["target_20_hit"] = True
                    reg["target_20_hit_time"] = x.ts.strftime("%H:%M")
                    reg["target_20_minutes"] = int((x.ts - bs[reg["si"]].ts).total_seconds() / 60)
                    reg["pre_target_mae_points"] = min(y.low for y in pre_target_bars) - reg["start_close"]
                    reg["pre_target_mfe_points"] = max(y.high for y in pre_target_bars) - reg["start_close"]
                    break
        if reg.get("target_20_hit"):
            hit_idx = None
            for j in range(reg["si"] + 1, len(bs)):
                if bs[j].ts.strftime("%H:%M") == reg.get("target_20_hit_time"):
                    hit_idx = j
                    break

            if hit_idx is not None:
                runner_bars = bs[hit_idx + 1:]
                final_points = bs[-1].close - reg["start_close"]
                for runner_target in (30, 40, 50):
                    prefix = f"runner_{runner_target}"
                    reg[f"{prefix}_outcome"] = "SESSION_END_EXIT"
                    reg[f"{prefix}_exit_time"] = bs[-1].ts.strftime("%H:%M")
                    reg[f"{prefix}_runner_points"] = final_points
                    for x in runner_bars:
                        hit_runner = x.high >= reg["start_close"] + float(runner_target)
                        hit_be = x.low <= reg["start_close"]
                        if hit_runner and hit_be:
                            reg[f"{prefix}_outcome"] = "AMBIGUOUS_SAME_CANDLE"
                            reg[f"{prefix}_exit_time"] = x.ts.strftime("%H:%M")
                            reg[f"{prefix}_runner_points"] = None
                            break
                        if hit_runner:
                            reg[f"{prefix}_outcome"] = "RUNNER_TARGET"
                            reg[f"{prefix}_exit_time"] = x.ts.strftime("%H:%M")
                            reg[f"{prefix}_runner_points"] = float(runner_target)
                            break
                        if hit_be:
                            reg[f"{prefix}_outcome"] = "BREAK_EVEN"
                            reg[f"{prefix}_exit_time"] = x.ts.strftime("%H:%M")
                            reg[f"{prefix}_runner_points"] = 0.0
                            break

                    rp = reg.get(f"{prefix}_runner_points")
                    reg[f"{prefix}_combined_50_50_points"] = (
                        10.0 + 0.5 * rp if rp is not None else None
                    )

        regimes.append(reg)

    if armed:
        events.append((bs[-1].ts.strftime("%H:%M"), "PATH1_ARMED_SESSION_CENSORED"))

    return events, regimes

def summarize_source(regimes, source):
    rows = [r for r in regimes if r["source"] == source]
    done = [r for r in rows if r.get("points_to_end") is not None]
    pts = [r["points_to_end"] for r in done]
    return {
        "regimes": len(rows),
        "completed": len(done),
        "censored": len(rows) - len(done),
        "positive": sum(x > 0 for x in pts),
        "negative": sum(x < 0 for x in pts),
        "net_points": sum(pts) if pts else None,
        "avg_points": mean(pts) if pts else None,
        "median_points": median(pts) if pts else None,
        "best_points": max(pts) if pts else None,
        "worst_points": min(pts) if pts else None,
        "positive_rate_pct": (sum(x > 0 for x in pts) / len(pts) * 100) if pts else None,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end-date", default="2026-09-21")
    ap.add_argument("--trading-sessions", type=int, default=120)
    ap.add_argument("--calendar-lookback-days", type=int, default=190)
    ap.add_argument("--output-dir", default="data/historical-evidence/branch-c-v2-9-full-exit-model")
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
    args = ap.parse_args()

    print("=== FROZEN ARCHITECTURE V2.9 ===")
    print("Opening path unchanged: 09:15 FULL -> 09:20 RSI>WMA -> 09:25 RSI>WMA")
    print("Path 1: RSI crosses EMA3 up -> ARMED")
    print("Confirm when RSI>WMA21 AND EMA3>WMA21 AND RSI slope UP AND EMA3 slope UP")
    print("IMPORTANT: RSI > 50 is NOT required for Path 1 in v2.9")
    print("Invalidation unchanged: RSI cross below WMA -> WEAKENING -> next candle still below = END")
    print()

    token = os.getenv(args.token_env)
    if not token:
        raise SystemExit(f"Missing {args.token_env}; load .env first")

    end = date.fromisoformat(args.end_date)
    start = end - timedelta(days=args.calendar_lookback_days)

    raw = {}
    d = start
    while d <= end:
        try:
            rows = fetch_1m(token, d)
            print(f"fetch {d}: candles={len(rows)}")
            if rows:
                raw[d] = rows
        except Exception as e:
            print(f"fetch {d}: ERROR {e}", file=sys.stderr)
        d += timedelta(days=1)

    dates = sorted(raw)
    if len(dates) < args.trading_sessions:
        raise SystemExit(
            f"Only {len(dates)} sessions available; need {args.trading_sessions}. "
            "Increase --calendar-lookback-days."
        )

    target = dates[-args.trading_sessions:]
    warmup = [x for x in dates if x < target[0]][-10:]

    all5 = []
    for sd in warmup + target:
        all5.extend(to5(raw[sd]))
    all5.sort(key=lambda b: b.ts)

    rs = rsi_wilder([b.close for b in all5])
    es = ema(rs)
    ws = wma(rs)
    for b, r, e, w in zip(all5, rs, es, ws):
        b.rsi, b.ema, b.wma = r, e, w

    by_day = {}
    for b in all5:
        if b.ts.date() in target:
            by_day.setdefault(b.ts.date(), []).append(b)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    regime_rows = []
    event_rows = []
    day_rows = []
    all_regimes = []

    for sd in target:
        events, regimes = replay(by_day.get(sd, []))
        all_regimes.extend(regimes)

        for t, ev in events:
            event_rows.append({
                "session_date": sd.isoformat(),
                "time": t,
                "event": ev,
            })

        for r in regimes:
            regime_rows.append({
                "session_date": sd.isoformat(),
                "source": r["source"],
                "armed_time": r.get("armed_time", ""),
                "bullish_start_time": r["start_time"],
                "bullish_start_close": f2(r["start_close"]),
                "bullish_end_time": r.get("end_time", ""),
                "bullish_end_close": f2(r.get("end_close")),
                "nifty_points_to_end": f2(r.get("points_to_end")),
                "duration_minutes": r.get("duration_minutes", ""),
                "mfe_points": f2(r.get("mfe_points")),
                "mae_points": f2(r.get("mae_points")),
                "target_20_price": f2(r.get("target_20_price")),
                "target_20_hit": "YES" if r.get("target_20_hit") else "NO",
                "target_20_hit_time": r.get("target_20_hit_time", ""),
                "target_20_minutes": "" if r.get("target_20_minutes") is None else r.get("target_20_minutes"),
                "pre_target_mae_points": f2(r.get("pre_target_mae_points")),
                "pre_target_mfe_points": f2(r.get("pre_target_mfe_points")),
                "runner_30_outcome": r.get("runner_30_outcome", ""),
                "runner_30_exit_time": r.get("runner_30_exit_time", ""),
                "runner_30_runner_points": f2(r.get("runner_30_runner_points")),
                "runner_30_combined_50_50_points": f2(r.get("runner_30_combined_50_50_points")),
                "runner_40_outcome": r.get("runner_40_outcome", ""),
                "runner_40_exit_time": r.get("runner_40_exit_time", ""),
                "runner_40_runner_points": f2(r.get("runner_40_runner_points")),
                "runner_40_combined_50_50_points": f2(r.get("runner_40_combined_50_50_points")),
                "runner_50_outcome": r.get("runner_50_outcome", ""),
                "runner_50_exit_time": r.get("runner_50_exit_time", ""),
                "runner_50_runner_points": f2(r.get("runner_50_runner_points")),
                "runner_50_combined_50_50_points": f2(r.get("runner_50_combined_50_50_points")),
                "nextbar_mfe_points": f2(r.get("nextbar_mfe_points")),
                "nextbar_mae_points": f2(r.get("nextbar_mae_points")),
                "sl_10_outcome": r.get("sl_10_outcome", ""),
                "sl_10_exit_time": r.get("sl_10_exit_time", ""),
                "sl_10_points": f2(r.get("sl_10_points")),
                "sl_15_outcome": r.get("sl_15_outcome", ""),
                "sl_15_exit_time": r.get("sl_15_exit_time", ""),
                "sl_15_points": f2(r.get("sl_15_points")),
                "sl_20_outcome": r.get("sl_20_outcome", ""),
                "sl_20_exit_time": r.get("sl_20_exit_time", ""),
                "sl_20_points": f2(r.get("sl_20_points")),
                "sl_25_outcome": r.get("sl_25_outcome", ""),
                "sl_25_exit_time": r.get("sl_25_exit_time", ""),
                "sl_25_points": f2(r.get("sl_25_points")),
                "sl_30_outcome": r.get("sl_30_outcome", ""),
                "sl_30_exit_time": r.get("sl_30_exit_time", ""),
                "sl_30_points": f2(r.get("sl_30_points")),
                "sl_40_outcome": r.get("sl_40_outcome", ""),
                "sl_40_exit_time": r.get("sl_40_exit_time", ""),
                "sl_40_points": f2(r.get("sl_40_points")),
                "sl_50_outcome": r.get("sl_50_outcome", ""),
                "sl_50_exit_time": r.get("sl_50_exit_time", ""),
                "sl_50_points": f2(r.get("sl_50_points")),
                "weakening_count": r.get("weakening_count", 0),
                "continuation_count": r.get("continuation_count", 0),
                "result": (
                    "SESSION_CENSORED"
                    if r.get("points_to_end") is None
                    else "POSITIVE" if r["points_to_end"] > 0
                    else "NEGATIVE" if r["points_to_end"] < 0
                    else "FLAT"
                ),
            })

        opening = summarize_source(regimes, "OPENING_PATH")
        path1 = summarize_source(regimes, "PATH_1_RSI_EMA_ARMED")

        completed = [r for r in regimes if r.get("points_to_end") is not None]
        total_pts = [r["points_to_end"] for r in completed]

        target20_rows = list(regimes)
        target20_hits = [r for r in target20_rows if r.get("target_20_hit")]
        target20_misses = [r for r in target20_rows if not r.get("target_20_hit")]

        day_rows.append({
            "session_date": sd.isoformat(),
            "target20_signals": len(target20_rows),
            "target20_hits": len(target20_hits),
            "target20_misses": len(target20_misses),
            "target20_hit_rate_pct": f"{(len(target20_hits)/len(target20_rows)*100):.2f}" if target20_rows else "",

            "opening_regimes": opening["regimes"],
            "opening_completed": opening["completed"],
            "opening_censored": opening["censored"],
            "opening_positive": opening["positive"],
            "opening_negative": opening["negative"],
            "opening_net_points": f2(opening["net_points"]),
            "opening_avg_points": f2(opening["avg_points"]),
            "opening_best_points": f2(opening["best_points"]),
            "opening_worst_points": f2(opening["worst_points"]),

            "path1_regimes": path1["regimes"],
            "path1_completed": path1["completed"],
            "path1_censored": path1["censored"],
            "path1_positive": path1["positive"],
            "path1_negative": path1["negative"],
            "path1_net_points": f2(path1["net_points"]),
            "path1_avg_points": f2(path1["avg_points"]),
            "path1_best_points": f2(path1["best_points"]),
            "path1_worst_points": f2(path1["worst_points"]),

            "total_regimes": len(regimes),
            "total_completed": len(completed),
            "total_censored": len(regimes) - len(completed),
            "total_net_points": f2(sum(total_pts)) if total_pts else "",
        })

    def write_csv(path, rows):
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write_csv(out / "branch-c-v2-9-partial-profit-regimes.csv", regime_rows)
    write_csv(out / "branch-c-v2-9-partial-profit-daywise.csv", day_rows)
    write_csv(out / "branch-c-v2-9-partial-profit-events.csv", event_rows)

    opening_summary = summarize_source(all_regimes, "OPENING_PATH")
    path1_summary = summarize_source(all_regimes, "PATH_1_RSI_EMA_ARMED")
    completed_all = [r for r in all_regimes if r.get("points_to_end") is not None]
    all_pts = [r["points_to_end"] for r in completed_all]

    stop_study = {}
    for stop_pts in (10, 15, 20, 25, 30, 40, 50):
        key = f"sl_{stop_pts}"
        target_count = 0
        stop_count = 0
        ambiguous_count = 0
        no_exit_count = 0
        realized_points = 0.0

        for r in all_regimes:
            outcome = r.get(f"{key}_outcome", "NO_EXIT")
            if outcome == "TARGET":
                target_count += 1
                realized_points += 20.0
            elif outcome == "STOP":
                stop_count += 1
                realized_points -= float(stop_pts)
            elif outcome == "AMBIGUOUS_SAME_CANDLE":
                ambiguous_count += 1
            else:
                no_exit_count += 1

        resolved = target_count + stop_count
        stop_study[str(stop_pts)] = {
            "stop_points": stop_pts,
            "target_points": 20.0,
            "resolved_signals": resolved,
            "target_first": target_count,
            "stop_first": stop_count,
            "ambiguous_same_candle": ambiguous_count,
            "no_exit_before_regime_end_or_session": no_exit_count,
            "target_first_rate_pct": (target_count / resolved * 100.0) if resolved else None,
            "net_points_resolved_only": realized_points,
            "avg_points_resolved_only": (realized_points / resolved) if resolved else None,
        }

    target20_winners = [r for r in all_regimes if r.get("target_20_hit")]
    winner_maes = [r.get("pre_target_mae_points") for r in target20_winners if r.get("pre_target_mae_points") is not None]

    def adverse_band(mae):
        if mae >= -5:
            return "0_to_-5"
        if mae >= -10:
            return "-5_to_-10"
        if mae >= -15:
            return "-10_to_-15"
        if mae >= -20:
            return "-15_to_-20"
        if mae >= -25:
            return "-20_to_-25"
        if mae >= -30:
            return "-25_to_-30"
        return "below_-30"

    adverse_distribution = {k: 0 for k in (
        "0_to_-5", "-5_to_-10", "-10_to_-15", "-15_to_-20",
        "-20_to_-25", "-25_to_-30", "below_-30"
    )}
    for mae in winner_maes:
        adverse_distribution[adverse_band(mae)] += 1

    partial_runner_study = {}
    for runner_target in (30, 40, 50):
        prefix = f"runner_{runner_target}"
        eligible = [r for r in all_regimes if r.get("target_20_hit")]
        target_n = sum(1 for r in eligible if r.get(f"{prefix}_outcome") == "RUNNER_TARGET")
        be_n = sum(1 for r in eligible if r.get(f"{prefix}_outcome") == "BREAK_EVEN")
        end_n = sum(1 for r in eligible if r.get(f"{prefix}_outcome") in ("END_EXIT", "SESSION_END_EXIT"))
        amb_n = sum(1 for r in eligible if r.get(f"{prefix}_outcome") == "AMBIGUOUS_SAME_CANDLE")
        vals = [
            r.get(f"{prefix}_combined_50_50_points")
            for r in eligible
            if r.get(f"{prefix}_combined_50_50_points") is not None
        ]
        partial_runner_study[str(runner_target)] = {
            "eligible_plus20_winners": len(eligible),
            "runner_target": runner_target,
            "book_at_plus20_fraction": 0.5,
            "runner_fraction": 0.5,
            "runner_stop_after_plus20": "BREAK_EVEN",
            "runner_check_starts": "NEXT_5M_CANDLE_AFTER_PLUS20_HIT_CANDLE",
            "runner_target_hits": target_n,
            "runner_break_even_exits": be_n,
            "runner_end_exits": end_n,
            "ambiguous_same_candle": amb_n,
            "combined_resolved_count": len(vals),
            "combined_total_points": sum(vals),
            "combined_avg_points": (sum(vals) / len(vals)) if vals else None,
        }

    # COMPLETE EXIT MODEL RESEARCH
    # Initial SL = -25 from the next 5m candle.
    # If +20 occurs before -25: book 50% at +20; runner 50% uses BE stop and +40 target.
    # If neither +20 nor -25 occurs before regime/session end: exit full size at regime-end/session-end close.
    # Any same-candle ordering ambiguity is preserved as AMBIGUOUS and excluded from resolved expectancy.
    full_model_rows = []
    for r in all_regimes:
        sl25 = r.get("sl_25_outcome", "NO_EXIT")
        row = {
            "session_date": r.get("session_date"),
            "source": r.get("source"),
            "bullish_start_time": r.get("start_time"),
            "start_close": r.get("start_close"),
            "sl25_outcome": sl25,
            "full_model_outcome": "",
            "full_model_points": None,
            "full_model_exit_time": "",
        }

        if sl25 == "STOP":
            row["full_model_outcome"] = "INITIAL_STOP_-25"
            row["full_model_points"] = -25.0
            row["full_model_exit_time"] = r.get("sl_25_exit_time", "")

        elif sl25 == "TARGET":
            runner_outcome = r.get("runner_40_outcome", "")
            combined = r.get("runner_40_combined_50_50_points")
            if runner_outcome == "AMBIGUOUS_SAME_CANDLE" or combined is None:
                row["full_model_outcome"] = "AMBIGUOUS_RUNNER_AFTER_+20"
                row["full_model_exit_time"] = r.get("runner_40_exit_time", "")
            else:
                row["full_model_outcome"] = f"+20_HALF_THEN_{runner_outcome}"
                row["full_model_points"] = combined
                row["full_model_exit_time"] = r.get("runner_40_exit_time", "")

        elif sl25 == "AMBIGUOUS_SAME_CANDLE":
            row["full_model_outcome"] = "AMBIGUOUS_INITIAL_+20_VS_-25"
            row["full_model_exit_time"] = r.get("sl_25_exit_time", "")

        else:
            # Neither +20 nor -25 before structural end/session end.
            if r.get("points_to_end") is not None:
                row["full_model_outcome"] = "STRUCTURAL_END_EXIT"
                row["full_model_points"] = r.get("points_to_end")
                row["full_model_exit_time"] = r.get("end_time", "")
            else:
                row["full_model_outcome"] = "SESSION_END_EXIT"
                row["full_model_points"] = r.get("session_end_points")
                row["full_model_exit_time"] = r.get("session_end_time", "")

        full_model_rows.append(row)

    full_resolved = [x for x in full_model_rows if x.get("full_model_points") is not None]
    full_ambiguous = [x for x in full_model_rows if x.get("full_model_points") is None]
    full_points = [x["full_model_points"] for x in full_resolved]

    full_model_summary = {
        "model": "SL_-25__50pct_at_+20__50pct_runner_to_+40_with_BE",
        "all_signals": len(full_model_rows),
        "resolved_signals": len(full_resolved),
        "ambiguous_signals": len(full_ambiguous),
        "positive": sum(x > 0 for x in full_points),
        "negative": sum(x < 0 for x in full_points),
        "flat": sum(x == 0 for x in full_points),
        "net_points": sum(full_points) if full_points else None,
        "avg_points": (sum(full_points) / len(full_points)) if full_points else None,
        "median_points": median(full_points) if full_points else None,
        "best_points": max(full_points) if full_points else None,
        "worst_points": min(full_points) if full_points else None,
        "positive_rate_pct": (
            sum(x > 0 for x in full_points) / len(full_points) * 100.0
            if full_points else None
        ),
        "outcome_counts": {},
    }
    for x in full_model_rows:
        k = x["full_model_outcome"]
        full_model_summary["outcome_counts"][k] = full_model_summary["outcome_counts"].get(k, 0) + 1

    target20_all = list(all_regimes)
    target20_hits = [r for r in target20_all if r.get("target_20_hit")]
    target20_misses = [r for r in target20_all if not r.get("target_20_hit")]
    target20_completed = list(completed_all)
    target20_completed_hits = [r for r in target20_completed if r.get("target_20_hit")]

    summary = {
        "model": "BRANCH_C_HILEGA_MILEGA_V2_9_PATH1_NO_RSI50_TARGET20",
        "sessions": len(target),
        "first_session": target[0].isoformat(),
        "last_session": target[-1].isoformat(),
        "complete_exit_model": full_model_summary,
        "partial_profit_runner_study": partial_runner_study,
        "pre_target_adverse_excursion": {
            "winner_signals": len(target20_winners),
            "measured_winners": len(winner_maes),
            "avg_pre_target_mae": (sum(winner_maes) / len(winner_maes)) if winner_maes else None,
            "worst_pre_target_mae": min(winner_maes) if winner_maes else None,
            "best_pre_target_mae": max(winner_maes) if winner_maes else None,
            "bands": adverse_distribution,
        },
        "stop_loss_study_target20": stop_study,
        "target_20_next_bar": {
            "target_points": 20.0,
            "check_starts": "NEXT_5M_CANDLE_AFTER_BULLISH_SIGNAL",
            "all_signals": len(target20_all),
            "hits": len(target20_hits),
            "misses": len(target20_misses),
            "hit_rate_pct": (len(target20_hits)/len(target20_all)*100) if target20_all else None,
            "completed_signals": len(target20_completed),
            "completed_hits": len(target20_completed_hits),
            "completed_hit_rate_pct": (len(target20_completed_hits)/len(target20_completed)*100) if target20_completed else None,
        },
        "opening": opening_summary,
        "path1": path1_summary,
        "combined": {
            "regimes": len(all_regimes),
            "completed": len(completed_all),
            "censored": len(all_regimes) - len(completed_all),
            "positive": sum(x > 0 for x in all_pts),
            "negative": sum(x < 0 for x in all_pts),
            "net_points": sum(all_pts) if all_pts else None,
            "avg_points": mean(all_pts) if all_pts else None,
            "median_points": median(all_pts) if all_pts else None,
            "best_points": max(all_pts) if all_pts else None,
            "worst_points": min(all_pts) if all_pts else None,
            "positive_rate_pct": (
                sum(x > 0 for x in all_pts) / len(all_pts) * 100
                if all_pts else None
            ),
        },
    }

    full_model_csv = out / "branch-c-v2-9-full-exit-model.csv"
    full_model_fields = [
        "session_date", "source", "bullish_start_time", "start_close",
        "sl25_outcome", "full_model_outcome", "full_model_points", "full_model_exit_time",
    ]
    with full_model_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=full_model_fields)
        w.writeheader()
        for row in full_model_rows:
            w.writerow({
                **row,
                "start_close": f2(row.get("start_close")),
                "full_model_points": f2(row.get("full_model_points")),
            })

    (out / "branch-c-v2-9-full-exit-model-summary.json").write_text(
        json.dumps(full_model_summary, indent=2), encoding="utf-8"
    )

    (out / "branch-c-v2-9-partial-profit-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("\n=== DAY-WISE SOURCE SEPARATION ===")
    print(
        f"{'DATE':10} | "
        f"{'OPEN REG':>8} {'OPEN DONE':>9} {'OPEN PTS':>10} | "
        f"{'P1 REG':>6} {'P1 DONE':>7} {'P1 PTS':>10} | "
        f"{'TOTAL PTS':>10}"
    )
    print("-" * 92)
    for r in day_rows:
        print(
            f"{r['session_date']:10} | "
            f"{r['opening_regimes']:8d} {r['opening_completed']:9d} {r['opening_net_points']:>10} | "
            f"{r['path1_regimes']:6d} {r['path1_completed']:7d} {r['path1_net_points']:>10} | "
            f"{r['total_net_points']:>10}"
        )

    print("\n=== COMPLETE EXIT MODEL ===")
    fm = summary["complete_exit_model"]
    print("Initial SL: -25")
    print("At +20 first: book 50%; runner 50% -> +40 with break-even stop")
    print("Neither +20 nor -25: exit at structural end; censored -> session end")
    print(f"all_signals={fm['all_signals']}")
    print(f"resolved_signals={fm['resolved_signals']}")
    print(f"ambiguous_signals={fm['ambiguous_signals']}")
    print(f"positive={fm['positive']}")
    print(f"negative={fm['negative']}")
    print(f"flat={fm['flat']}")
    print(f"net_points={fm['net_points']:.2f}" if fm["net_points"] is not None else "net_points=n/a")
    print(f"avg_points={fm['avg_points']:.4f}" if fm["avg_points"] is not None else "avg_points=n/a")
    print(f"median_points={fm['median_points']:.2f}" if fm["median_points"] is not None else "median_points=n/a")
    print(f"best_points={fm['best_points']:.2f}" if fm["best_points"] is not None else "best_points=n/a")
    print(f"worst_points={fm['worst_points']:.2f}" if fm["worst_points"] is not None else "worst_points=n/a")
    print(f"positive_rate_pct={fm['positive_rate_pct']:.2f}" if fm["positive_rate_pct"] is not None else "positive_rate_pct=n/a")
    print("outcome_counts=" + json.dumps(fm["outcome_counts"], sort_keys=True))

    print("\n=== PARTIAL PROFIT STUDY: 50% AT +20, 50% RUNNER WITH BE STOP ===")
    print(f"{'RUNNER':>7} | {'ELIG':>4} {'TGT':>4} {'BE':>4} {'END':>4} {'AMB':>4} {'TOTAL PTS':>10} {'AVG':>8}")
    print("-" * 70)
    for runner_target in (30, 40, 50):
        s = summary["partial_profit_runner_study"][str(runner_target)]
        print(
            f"+{runner_target:6d} | "
            f"{s['eligible_plus20_winners']:4d} "
            f"{s['runner_target_hits']:4d} "
            f"{s['runner_break_even_exits']:4d} "
            f"{s['runner_end_exits']:4d} "
            f"{s['ambiguous_same_candle']:4d} "
            f"{s['combined_total_points']:10.2f} "
            f"{s['combined_avg_points']:8.3f}"
        )

    print("\n=== +20 WINNERS: ADVERSE EXCURSION BEFORE TARGET ===")
    s = summary["pre_target_adverse_excursion"]
    print(f"Winners measured: {s['measured_winners']}")
    if s["avg_pre_target_mae"] is not None:
        print(f"Average pre-target MAE: {s['avg_pre_target_mae']:.2f}")
        print(f"Worst pre-target MAE: {s['worst_pre_target_mae']:.2f}")
    print()
    print(f"{'ADVERSE MOVE':>14} | {'COUNT':>5} | {'PCT':>7}")
    print("-" * 34)
    for label in ("0_to_-5", "-5_to_-10", "-10_to_-15", "-15_to_-20", "-20_to_-25", "-25_to_-30", "below_-30"):
        c = s["bands"][label]
        pct = (c / s["measured_winners"] * 100.0) if s["measured_winners"] else 0.0
        print(f"{label:>14} | {c:5d} | {pct:6.2f}%")

    print("\n=== +20 TARGET vs STOP-LOSS FIRST-TOUCH STUDY ===")
    print(f"{'SL':>5} | {'RES':>4} {'TGT1':>5} {'SL1':>5} {'AMB':>4} {'NOEX':>4} {'TGT1%':>7} {'NET':>10} {'AVG':>8}")
    print("-" * 72)
    for stop_pts in (10, 15, 20, 25, 30, 40, 50):
        s = summary["stop_loss_study_target20"][str(stop_pts)]
        print(
            f"{stop_pts:5d} | "
            f"{s['resolved_signals']:4d} "
            f"{s['target_first']:5d} "
            f"{s['stop_first']:5d} "
            f"{s['ambiguous_same_candle']:4d} "
            f"{s['no_exit_before_regime_end_or_session']:4d} "
            f"{s['target_first_rate_pct']:7.2f} "
            f"{s['net_points_resolved_only']:10.2f} "
            f"{s['avg_points_resolved_only']:8.3f}"
        )

    print("\n=== +20 TARGET SUMMARY (NEXT 5M CANDLE ONWARD) ===")
    print(json.dumps(summary["target_20_next_bar"], indent=2))

    print("\n=== +20 TARGET DAY-WISE ===")
    print(f"{'DATE':10} | {'SIG':>4} {'HIT':>4} {'MISS':>4} {'HIT%':>7}")
    print("-" * 38)
    for r in day_rows:
        print(f"{r['session_date']:10} | {r['target20_signals']:4d} {r['target20_hits']:4d} {r['target20_misses']:4d} {r['target20_hit_rate_pct']:>7}")

    print("\n=== OPENING SUMMARY ===")
    print(json.dumps(opening_summary, indent=2))

    print("\n=== PATH 1 SUMMARY ===")
    print(json.dumps(path1_summary, indent=2))

    print("\n=== COMBINED SUMMARY ===")
    print(json.dumps(summary["combined"], indent=2))

    print("\n=== REGIME DETAIL ===")
    for r in regime_rows:
        print(r)

    print("\nOutputs:")
    print(out / "branch-c-v2-9-partial-profit-daywise.csv")
    print(out / "branch-c-v2-9-partial-profit-regimes.csv")
    print(out / "branch-c-v2-9-partial-profit-events.csv")
    print(out / "branch-c-v2-9-partial-profit-summary.json")

if __name__ == "__main__":
    main()
