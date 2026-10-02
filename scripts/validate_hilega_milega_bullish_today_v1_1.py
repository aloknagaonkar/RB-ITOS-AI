from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

MODEL = "HILEGA_MILEGA_BULLISH_TODAY_V1_1"
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def pine_rsi(values: list[float], length: int = 9) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= length:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, length + 1):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length

    def calc(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        if g == 0:
            return 0.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[length] = calc(avg_gain, avg_loss)
    for i in range(length + 1, len(values)):
        d = values[i] - values[i - 1]
        gain = max(d, 0.0)
        loss = max(-d, 0.0)
        avg_gain = (avg_gain * (length - 1) + gain) / length
        avg_loss = (avg_loss * (length - 1) + loss) / length
        out[i] = calc(avg_gain, avg_loss)
    return out


def ema(values: list[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    alpha = 2.0 / (length + 1.0)
    prev: float | None = None
    for i, value in enumerate(values):
        if value is None:
            continue
        prev = value if prev is None else alpha * value + (1.0 - alpha) * prev
        out[i] = prev
    return out


def wma(values: list[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    weights = list(range(1, length + 1))
    denom = sum(weights)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(float(v) * w for v, w in zip(window, weights)) / denom
    return out


def strict_bullish(
    prev_rsi: float,
    prev_ema: float,
    prev_wma: float,
    rsi: float,
    ema3: float,
    wma21: float,
    *,
    require_upward_slopes: bool = True,
) -> bool:
    # Condition 1: RSI crosses EMA3 upward on this candle.
    c1 = prev_rsi <= prev_ema and rsi > ema3
    # Condition 2: BOTH RSI and EMA3 cross WMA21 upward on this candle.
    c2 = (
        prev_rsi <= prev_wma
        and rsi > wma21
        and prev_ema <= prev_wma
        and ema3 > wma21
    )
    slopes = (
        rsi > prev_rsi and ema3 > prev_ema and wma21 > prev_wma
    )
    return c1 and c2 and (slopes if require_upward_slopes else True)


def _fetch(client: httpx.Client, token: str, path: str) -> list[list]:
    r = client.get(
        path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"Upstox HTTP {r.status_code}: {r.text[:500]}")
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox response status={body.get('status')!r}")
    return body.get("data", {}).get("candles", [])


def parse_1m(raw: list[list]) -> list[dict]:
    rows: list[dict] = []
    for x in raw:
        ts = datetime.fromisoformat(x[0]).astimezone(IST)
        mins = ts.hour * 60 + ts.minute
        if mins < 9 * 60 + 15 or mins > 15 * 60 + 29:
            continue
        rows.append(
            {
                "ts": ts,
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
            }
        )
    rows.sort(key=lambda r: r["ts"])
    return rows


def make_5m(rows: list[dict]) -> list[dict]:
    buckets: dict[datetime, list[dict]] = {}
    for r in rows:
        ts = r["ts"]
        offset = (ts.hour * 60 + ts.minute) - (9 * 60 + 15)
        if offset < 0:
            continue
        bucket_offset = (offset // 5) * 5
        total = 9 * 60 + 15 + bucket_offset
        start = ts.replace(hour=total // 60, minute=total % 60, second=0, microsecond=0)
        buckets.setdefault(start, []).append(r)

    out: list[dict] = []
    for start in sorted(buckets):
        b = sorted(buckets[start], key=lambda r: r["ts"])
        if len(b) != 5:
            continue
        exact = True
        for i, row in enumerate(b):
            total = start.hour * 60 + start.minute + i
            if row["ts"].hour != total // 60 or row["ts"].minute != total % 60:
                exact = False
                break
        if not exact:
            continue
        out.append(
            {
                "start": start,
                "end": b[-1]["ts"],
                "open": b[0]["open"],
                "high": max(x["high"] for x in b),
                "low": min(x["low"] for x in b),
                "close": b[-1]["close"],
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--session-date", required=True)
    ap.add_argument("--warmup-date", action="append", default=[])
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/branch-c-hilega-milega-bullish-v1-1",
    )
    ap.add_argument(
        "--no-slope-filter",
        action="store_true",
        help="Diagnostic only: disable the previously requested all-three-lines-upward condition.",
    )
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing")

    encoded = quote(args.underlying, safe="")
    all_raw: list[list] = []
    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        for day in args.warmup_date:
            path = f"/v3/historical-candle/{encoded}/minutes/1/{day}/{day}"
            candles = _fetch(client, token, path)
            print(f"warmup {day}: candles={len(candles)}")
            all_raw.extend(candles)

        # This validator is intentionally for the current trading day.
        path = f"/v3/historical-candle/intraday/{encoded}/minutes/1"
        candles = _fetch(client, token, path)
        print(f"intraday {args.session_date}: candles={len(candles)}")
        all_raw.extend(candles)

    bars = make_5m(parse_1m(all_raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    rows: list[dict] = []
    for i in range(1, len(bars)):
        if bars[i]["start"].date().isoformat() != args.session_date:
            continue
        vals = (rsi9[i - 1], ema3[i - 1], wma21[i - 1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue
        pr, pe, pw, r, e, w = (float(v) for v in vals)
        c1 = pr <= pe and r > e
        c2_rsi = pr <= pw and r > w
        c2_ema = pe <= pw and e > w
        slope_rsi = r > pr
        slope_ema = e > pe
        slope_wma = w > pw
        signal = strict_bullish(
            pr, pe, pw, r, e, w,
            require_upward_slopes=not args.no_slope_filter,
        )
        if signal:
            rows.append(
                {
                    "candle_start": bars[i]["start"].isoformat(),
                    "candle_end": bars[i]["end"].isoformat(),
                    "close": bars[i]["close"],
                    "rsi9": r,
                    "ema3_rsi": e,
                    "wma21_rsi": w,
                    "prev_rsi9": pr,
                    "prev_ema3_rsi": pe,
                    "prev_wma21_rsi": pw,
                    "condition1_rsi_cross_ema_up": c1,
                    "condition2_rsi_cross_wma_up": c2_rsi,
                    "condition2_ema_cross_wma_up": c2_ema,
                    "rsi_slope_up": slope_rsi,
                    "ema3_slope_up": slope_ema,
                    "wma21_slope_up": slope_wma,
                }
            )

    print("\n=== STRICT BULLISH CANDLE TIMINGS TO VALIDATE ON CHART ===\n")
    if not rows:
        print("NO STRICT BULLISH SIGNALS FOUND")
    else:
        for n, row in enumerate(rows, 1):
            s = datetime.fromisoformat(row["candle_start"])
            e = datetime.fromisoformat(row["candle_end"])
            print(
                f"{n:02d}. {s:%H:%M}-{e:%H:%M} close={row['close']:.2f} "
                f"RSI9={row['rsi9']:.4f} EMA3={row['ema3_rsi']:.4f} WMA21={row['wma21_rsi']:.4f}"
            )
            print(
                f"    prev RSI9={row['prev_rsi9']:.4f} EMA3={row['prev_ema3_rsi']:.4f} "
                f"WMA21={row['prev_wma21_rsi']:.4f}"
            )
            print("    C1 RSI↑EMA3=Y | C2 RSI↑WMA=Y EMA3↑WMA=Y | slopes RSI/EMA3/WMA=Y/Y/Y")

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / f"bullish-signals-{args.session_date}-v1-1.csv"
    json_path = outdir / f"bullish-signals-{args.session_date}-v1-1.json"

    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    json_path.write_text(
        json.dumps(
            {
                "model": MODEL,
                "session_date": args.session_date,
                "rule": {
                    "condition_1": "RSI9 crosses EMA3(RSI9) upward on the same completed 5m candle",
                    "condition_2": "RSI9 and EMA3(RSI9) both cross WMA21(RSI9) upward on that same completed 5m candle",
                    "upward_slopes_required": not args.no_slope_filter,
                },
                "signal_count": len(rows),
                "signals": rows,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"\n5m bars={len(bars)} strict_bullish_signals={len(rows)}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
