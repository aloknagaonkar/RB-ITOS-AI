#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, os, sys, urllib.parse, urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
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

def fetch_historical_1m(token: str, sd: date) -> list[Bar]:
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
            open=float(c.open), high=float(c.high),
            low=float(c.low), close=float(c.close),
            volume=None if c.volume is None else int(c.volume),
            oi=None if c.open_interest is None else int(c.open_interest),
        ))
    return sorted(out, key=lambda b: b.ts)

def fetch_intraday_1m(token: str, sd: date) -> list[Bar]:
    encoded = urllib.parse.quote(UNDERLYING, safe="")
    url = f"https://api.upstox.com/v3/historical-candle/intraday/{encoded}/minutes/1"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    rows = payload.get("data", {}).get("candles", [])
    out = []
    for r in rows:
        if len(r) < 5:
            continue
        ts = datetime.fromisoformat(str(r[0]).replace("Z", "+00:00")).astimezone(IST)
        if ts.date() != sd:
            continue
        out.append(Bar(
            ts=ts,
            open=float(r[1]), high=float(r[2]),
            low=float(r[3]), close=float(r[4]),
            volume=int(r[5]) if len(r) > 5 and r[5] is not None else None,
            oi=int(r[6]) if len(r) > 6 and r[6] is not None else None,
        ))
    return sorted(out, key=lambda b: b.ts)

def fetch_1m(token: str, sd: date) -> list[Bar]:
    today_ist = datetime.now(IST).date()
    if sd == today_ist:
        try:
            rows = fetch_intraday_1m(token, sd)
            if rows:
                return rows
        except Exception as e:
            print(f"intraday fetch {sd}: ERROR {e}", file=sys.stderr)
    return fetch_historical_1m(token, sd)

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

def yn(v): return "Y" if v else "N"
def f2(v): return "" if v is None else f"{v:.2f}"

def replay_immediate_exit(bs: list[Bar], sd: date):
    rows, events = [], []
    active = armed = opening_candidate = opening_holding = False
    source = entry_time = armed_time = ""
    entry_close = None

    for i, b in enumerate(bs):
        prev = bs[i-1] if i else None
        t = b.ts.strftime("%H:%M")
        event = ""

        if None in (b.rsi, b.ema, b.wma):
            rows.append({
                "session_date": sd.isoformat(), "time": t,
                "open": f2(b.open), "high": f2(b.high), "low": f2(b.low), "close": f2(b.close),
                "rsi9": f2(b.rsi), "ema3_rsi": f2(b.ema), "wma21_rsi": f2(b.wma),
                "rsi_gt_ema": "", "rsi_gt_50": "", "rsi_gt_wma": "", "ema_gt_wma": "",
                "rsi_slope_up": "", "ema_slope_up": "", "rsi_cross_ema_up": "",
                "rsi_cross_wma_down": "", "full_alignment": "", "armed": yn(armed),
                "active": yn(active), "source": source, "entry_time": entry_time,
                "entry_close": f2(entry_close), "points_from_entry_close": "",
                "event": "INDICATOR_WARMUP",
            })
            continue

        rsi_up = bool(prev and prev.rsi is not None and b.rsi > prev.rsi)
        ema_up = bool(prev and prev.ema is not None and b.ema > prev.ema)
        rsi_cross_ema = bool(prev and cross_up(prev.rsi, prev.ema, b.rsi, b.ema))
        rsi_cross_down_wma = bool(prev and cross_down(prev.rsi, prev.wma, b.rsi, b.wma))

        # Immediate exit on first RSI cross below WMA21.
        if active and rsi_cross_down_wma:
            event = "EXIT_RSI_CROSS_BELOW_WMA21"
            events.append((t, event, source, entry_time, entry_close, b.close, b.close - entry_close))
            active = False
            source = entry_time = armed_time = ""
            entry_close = None
            armed = False

        # Opening path unchanged.
        if t == "09:15" and full_alignment(b):
            opening_candidate = True
            event = event or "OPENING_ALIGNMENT"
        elif t == "09:20" and opening_candidate:
            if b.rsi > b.wma:
                opening_holding = True
                event = event or "OPENING_HOLDING"
            else:
                opening_candidate = opening_holding = False
                event = event or "OPENING_REJECTED_0920"
        elif t == "09:25" and opening_candidate and opening_holding:
            if b.rsi > b.wma and not active:
                active = True
                source = "OPENING_PATH"
                entry_time, entry_close = t, b.close
                armed = False
                event = event or "ENTRY_OPENING_BULLISH_CONFIRMED"
                events.append((t, event, source, entry_time, entry_close, None, None))
            else:
                event = event or "OPENING_REJECTED_0925"
            opening_candidate = opening_holding = False

        # RSI crosses EMA3 upward -> armed.
        if not active and rsi_cross_ema:
            armed, armed_time = True, t

            # Route A: fresh RSI cross above EMA3 AND RSI > 50 AND RSI > WMA21.
            if b.rsi > 50 and b.rsi > b.wma:
                active = True
                source = "PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"
                entry_time, entry_close = t, b.close
                armed = False
                event = event or "ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"
                events.append((t, event, source, entry_time, entry_close, None, None))
            else:
                event = event or "PATH1_ARMED_RSI_CROSS_EMA3_UP"

        # Route B: after arming, structural/rising confirmation.
        if (not active and armed
            and (b.rsi > b.wma or b.ema > b.wma)
            and rsi_up and ema_up):
            active = True
            source = "PATH1_ROUTE_B_STRUCTURAL"
            entry_time, entry_close = t, b.close
            armed = False
            event = event or "ENTRY_PATH1_ROUTE_B_STRUCTURAL"
            events.append((t, event, source, entry_time, entry_close, None, None))

        points = None if entry_close is None else b.close - entry_close
        rows.append({
            "session_date": sd.isoformat(), "time": t,
            "open": f2(b.open), "high": f2(b.high), "low": f2(b.low), "close": f2(b.close),
            "rsi9": f2(b.rsi), "ema3_rsi": f2(b.ema), "wma21_rsi": f2(b.wma),
            "rsi_gt_ema": yn(b.rsi > b.ema), "rsi_gt_50": yn(b.rsi > 50),
            "rsi_gt_wma": yn(b.rsi > b.wma), "ema_gt_wma": yn(b.ema > b.wma),
            "rsi_slope_up": yn(rsi_up), "ema_slope_up": yn(ema_up),
            "rsi_cross_ema_up": yn(rsi_cross_ema), "rsi_cross_wma_down": yn(rsi_cross_down_wma),
            "full_alignment": yn(full_alignment(b)), "armed": yn(armed), "active": yn(active),
            "source": source, "entry_time": entry_time, "entry_close": f2(entry_close),
            "points_from_entry_close": f2(points), "event": event,
        })

    if active:
        events.append((bs[-1].ts.strftime("%H:%M"), "SESSION_CENSORED_ACTIVE",
                       source, entry_time, entry_close, bs[-1].close, bs[-1].close-entry_close))
    return rows, events

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="+", default=["2026-09-17", "2026-09-18", "2026-09-21"])
    ap.add_argument("--warmup-calendar-days", type=int, default=45)
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
    ap.add_argument("--output-dir", default="data/historical-evidence/hilega-milega-final-entry-exit-chart-check")
    args = ap.parse_args()

    token = os.getenv(args.token_env)
    if not token:
        raise SystemExit(f"Missing {args.token_env}; load .env first")

    target_dates = [date.fromisoformat(x) for x in args.dates]
    first = min(target_dates)
    last = max(target_dates)
    start = first - timedelta(days=args.warmup_calendar_days)

    raw = {}
    d = start
    while d <= last:
        try:
            bars = fetch_1m(token, d)
            print(f"fetch {d}: candles={len(bars)}")
            if bars:
                raw[d] = bars
        except Exception as e:
            print(f"fetch {d}: ERROR {e}", file=sys.stderr)
        d += timedelta(days=1)

    missing = [d.isoformat() for d in target_dates if d not in raw]
    if missing:
        raise SystemExit(f"Missing target-session data: {', '.join(missing)}")

    prior_sessions = sorted(d for d in raw if d < first)[-10:]
    calc_dates = prior_sessions + sorted(target_dates)

    all5 = []
    for sd in calc_dates:
        all5.extend(to5(raw[sd]))
    all5.sort(key=lambda b: b.ts)

    rs = rsi_wilder([b.close for b in all5], 9)
    es = ema(rs, 3)
    ws = wma(rs, 21)
    for b, r, e, w in zip(all5, rs, es, ws):
        b.rsi, b.ema, b.wma = r, e, w

    by_day = {}
    for b in all5:
        by_day.setdefault(b.ts.date(), []).append(b)

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    event_rows = []

    for sd in target_dates:
        rows, events = replay_immediate_exit(by_day.get(sd, []), sd)
        all_rows.extend(rows)

        print(f"\n=== {sd} PER-CANDLE CHECK ===")
        print(
            f"{'TIME':5} {'CLOSE':>9} {'RSI9':>8} {'EMA3':>8} {'WMA21':>8} "
            f"{'R>E':>4} {'R>50':>4} {'R>W':>4} {'E>W':>4} {'RUP':>4} {'EUP':>4} {'ACTIVE':>6} EVENT"
        )
        print("-" * 108)
        for r in rows:
            print(
                f"{r['time']:5} {r['close']:>9} {r['rsi9']:>8} {r['ema3_rsi']:>8} {r['wma21_rsi']:>8} "
                f"{r['rsi_gt_ema']:>4} {r['rsi_gt_50']:>4} {r['rsi_gt_wma']:>4} {r['ema_gt_wma']:>4} "
                f"{r['rsi_slope_up']:>4} {r['ema_slope_up']:>4} {r['active']:>6} {r['event']}"
            )

        print(f"\n=== {sd} ENTRY / EXIT EVENTS ===")
        if not events:
            print("NO EVENTS")
        for ev in events:
            t, name, source, et, ep, xp, pts = ev
            print(
                f"{t} | {name} | source={source} | entry={et} @ {f2(ep)}"
                + ("" if xp is None else f" | exit_close={f2(xp)} | points={f2(pts)}")
            )
            event_rows.append({
                "session_date": sd.isoformat(),
                "time": t,
                "event": name,
                "source": source,
                "entry_time": et,
                "entry_close": f2(ep),
                "exit_close": f2(xp),
                "points_signal_close_to_exit_close": f2(pts),
            })

    def write_csv(path: Path, rows):
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write_csv(outdir / "per-candle.csv", all_rows)
    write_csv(outdir / "events.csv", event_rows)

    print(f"\nCSV per candle: {outdir / 'per-candle.csv'}")
    print(f"CSV events:     {outdir / 'events.csv'}")
    print("\nNOTE: Entry/exit P&L here uses signal-candle close for chart validation only.")
    print("Executable backtest should separately use next-bar OPEN.")

if __name__ == "__main__":
    main()
