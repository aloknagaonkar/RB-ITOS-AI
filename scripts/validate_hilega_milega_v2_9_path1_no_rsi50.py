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
    ap.add_argument("--output-dir", default="data/historical-evidence/branch-c-v2-9-path1-no-rsi50")
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

        day_rows.append({
            "session_date": sd.isoformat(),

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

    write_csv(out / "branch-c-v2-9-regimes-daywise.csv", regime_rows)
    write_csv(out / "branch-c-v2-9-daywise-source-separation.csv", day_rows)
    write_csv(out / "branch-c-v2-9-events.csv", event_rows)

    opening_summary = summarize_source(all_regimes, "OPENING_PATH")
    path1_summary = summarize_source(all_regimes, "PATH_1_RSI_EMA_ARMED")
    completed_all = [r for r in all_regimes if r.get("points_to_end") is not None]
    all_pts = [r["points_to_end"] for r in completed_all]

    summary = {
        "model": "BRANCH_C_HILEGA_MILEGA_V2_9_PATH1_NO_RSI50",
        "sessions": len(target),
        "first_session": target[0].isoformat(),
        "last_session": target[-1].isoformat(),
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

    (out / "branch-c-v2-9-summary.json").write_text(
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
    print(out / "branch-c-v2-9-daywise-source-separation.csv")
    print(out / "branch-c-v2-9-regimes-daywise.csv")
    print(out / "branch-c-v2-9-events.csv")
    print(out / "branch-c-v2-9-summary.json")

if __name__ == "__main__":
    main()
