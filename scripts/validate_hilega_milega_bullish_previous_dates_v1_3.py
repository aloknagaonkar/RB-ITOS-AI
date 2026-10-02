from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_hilega_milega_bullish_today_v1_1 import (
    ema,
    make_5m,
    parse_1m,
    pine_rsi,
    wma,
)
from scripts.validate_hilega_milega_bullish_transition_audit_v1_2 import (
    detect_upward_transitions,
)

MODEL = "HILEGA_MILEGA_BULLISH_PREVIOUS_DATES_V1_3"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def detect_sequence_confirmations(
    bars: list[dict],
    rsi9: list[float | None],
    ema3: list[float | None],
    wma21: list[float | None],
    session_date: str,
) -> list[dict]:
    """Detect the frozen Branch-C bullish sequence with NO duration cutoff.

    Sequence:
      1) RSI9 crosses EMA3(RSI9) upward. This opens a candidate.
      2) After that crossover, wait for BOTH:
           - RSI9 crosses WMA21(RSI9) upward
           - EMA3(RSI9) crosses WMA21(RSI9) upward
         The WMA crossings may occur on the same or different later candles.
      3) The confirmation candle is the candle where the last required WMA
         crossover occurs, provided RSI9, EMA3 and WMA21 are all sloping up.
      4) Record elapsed bars/minutes. Duration is descriptive only and never
         rejects a candidate.

    WMA crossings that occur before Condition 1 are ignored. If another
    RSI9↑EMA3 crossover occurs while a candidate is still open, the latest
    crossover becomes the active start. This avoids carrying a stale setup
    through a later momentum reset without imposing a time limit.
    """
    confirmations: list[dict] = []
    active: dict | None = None

    for i in range(1, len(bars)):
        if bars[i]["start"].date().isoformat() != session_date:
            continue

        vals = (rsi9[i - 1], ema3[i - 1], wma21[i - 1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue
        pr, pe, pw, r, e, w = (float(v) for v in vals)
        flags = detect_upward_transitions(pr, pe, pw, r, e, w)

        if flags["rsi_cross_ema_up"]:
            active = {
                "start_index": i,
                "condition1_time": bars[i]["start"],
                "rsi_wma_time": None,
                "ema_wma_time": None,
            }

        if active is None:
            continue

        if flags["rsi_cross_wma_up"] and active["rsi_wma_time"] is None:
            active["rsi_wma_time"] = bars[i]["start"]
        if flags["ema_cross_wma_up"] and active["ema_wma_time"] is None:
            active["ema_wma_time"] = bars[i]["start"]

        complete = active["rsi_wma_time"] is not None and active["ema_wma_time"] is not None
        slopes_up = flags["rsi_slope_up"] and flags["ema3_slope_up"] and flags["wma21_slope_up"]

        if complete and slopes_up:
            sequence_bars = i - active["start_index"]
            confirmations.append(
                {
                    "session_date": session_date,
                    "condition1_time": active["condition1_time"].isoformat(),
                    "rsi_wma_time": active["rsi_wma_time"].isoformat(),
                    "ema_wma_time": active["ema_wma_time"].isoformat(),
                    "confirmation_time": bars[i]["start"].isoformat(),
                    "candle_end": bars[i]["end"].isoformat(),
                    "sequence_bars": sequence_bars,
                    "sequence_minutes": sequence_bars * 5,
                    "close": bars[i]["close"],
                    "rsi9": r,
                    "ema3_rsi": e,
                    "wma21_rsi": w,
                    "rsi_slope_up": flags["rsi_slope_up"],
                    "ema3_slope_up": flags["ema3_slope_up"],
                    "wma21_slope_up": flags["wma21_slope_up"],
                }
            )
            active = None

    return confirmations


def _fetch(client: httpx.Client, token: str, encoded: str, day: str) -> list[list]:
    path = f"/v3/historical-candle/{encoded}/minutes/1/{day}/{day}"
    r = client.get(
        path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"Upstox {day} HTTP {r.status_code}: {r.text[:500]}")
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox {day} response status={body.get('status')!r}")
    return body.get("data", {}).get("candles", [])


def date_range(start: date, end: date) -> list[date]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--session-date", action="append", required=True)
    ap.add_argument("--warmup-calendar-days", type=int, default=7)
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/branch-c-hilega-milega-bullish-v1-3",
    )
    args = ap.parse_args()

    targets = sorted({date.fromisoformat(x) for x in args.session_date})

    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing")

    encoded = quote(args.underlying, safe="")
    fetch_start = min(targets) - timedelta(days=args.warmup_calendar_days)
    fetch_end = max(targets)

    all_raw: list[list] = []
    fetch_errors: list[dict] = []
    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        for d in date_range(fetch_start, fetch_end):
            day = d.isoformat()
            try:
                candles = _fetch(client, token, encoded, day)
                print(f"fetch {day}: candles={len(candles)}")
                all_raw.extend(candles)
            except Exception as exc:
                print(f"fetch {day}: ERROR {exc}")
                fetch_errors.append({"date": day, "error": str(exc)})

    bars = make_5m(parse_1m(all_raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    all_confirmations: list[dict] = []
    print("\n=== BRANCH C BULLISH CONFIRMATIONS — PREVIOUS DATES ===\n")
    for target in targets:
        day = target.isoformat()
        rows = detect_sequence_confirmations(bars, rsi9, ema3, wma21, day)
        all_confirmations.extend(rows)
        print(f"{day}: confirmations={len(rows)}")
        if not rows:
            print("  NONE")
            continue
        for n, row in enumerate(rows, 1):
            c1 = datetime.fromisoformat(row["condition1_time"])
            rw = datetime.fromisoformat(row["rsi_wma_time"])
            ew = datetime.fromisoformat(row["ema_wma_time"])
            cf = datetime.fromisoformat(row["confirmation_time"])
            ce = datetime.fromisoformat(row["candle_end"])
            print(
                f"  {n:02d}. CONFIRM {cf:%H:%M}-{ce:%H:%M} "
                f"C1(RSI↑EMA3)={c1:%H:%M} RSI↑WMA={rw:%H:%M} "
                f"EMA3↑WMA={ew:%H:%M} duration={row['sequence_minutes']}m "
                f"close={row['close']:.2f} RSI9={row['rsi9']:.4f} "
                f"EMA3={row['ema3_rsi']:.4f} WMA21={row['wma21_rsi']:.4f}"
            )

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "bullish-confirmations-v1-3.csv"
    json_path = outdir / "bullish-confirmations-v1-3.json"

    if all_confirmations:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_confirmations[0].keys()))
            writer.writeheader()
            writer.writerows(all_confirmations)
    else:
        csv_path.write_text("", encoding="utf-8")

    json_path.write_text(
        json.dumps(
            {
                "model": MODEL,
                "rule": {
                    "condition_1": "RSI9 crosses EMA3(RSI9) upward first",
                    "condition_2": "After Condition 1, RSI9 and EMA3(RSI9) each cross WMA21(RSI9) upward",
                    "duration_filter": None,
                    "duration_is_descriptive_only": True,
                    "confirmation": "last required WMA crossover, with RSI9/EMA3/WMA21 all sloping upward",
                },
                "session_dates": [d.isoformat() for d in targets],
                "confirmation_count": len(all_confirmations),
                "confirmations": all_confirmations,
                "fetch_errors": fetch_errors,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"\nconfirmation_count={len(all_confirmations)}")
    print("No maximum sequence duration is imposed in V1.3; duration is reported only.")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
