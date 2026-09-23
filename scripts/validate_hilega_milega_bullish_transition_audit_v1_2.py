from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from scripts.validate_hilega_milega_bullish_today_v1_1 import (
    ema,
    make_5m,
    parse_1m,
    pine_rsi,
    wma,
)

MODEL = "HILEGA_MILEGA_BULLISH_TRANSITION_AUDIT_V1_2"
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def detect_upward_transitions(
    prev_rsi: float,
    prev_ema: float,
    prev_wma: float,
    rsi: float,
    ema3: float,
    wma21: float,
) -> dict[str, bool]:
    return {
        "rsi_cross_ema_up": prev_rsi <= prev_ema and rsi > ema3,
        "rsi_cross_wma_up": prev_rsi <= prev_wma and rsi > wma21,
        "ema_cross_wma_up": prev_ema <= prev_wma and ema3 > wma21,
        "rsi_slope_up": rsi > prev_rsi,
        "ema3_slope_up": ema3 > prev_ema,
        "wma21_slope_up": wma21 > prev_wma,
    }


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


def main() -> int:
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--session-date", required=True)
    ap.add_argument("--warmup-date", action="append", default=[])
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/branch-c-hilega-milega-transition-v1-2",
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

        vals = (
            rsi9[i - 1], ema3[i - 1], wma21[i - 1],
            rsi9[i], ema3[i], wma21[i],
        )
        if any(v is None for v in vals):
            continue

        pr, pe, pw, r, e, w = (float(v) for v in vals)
        flags = detect_upward_transitions(pr, pe, pw, r, e, w)

        if not (
            flags["rsi_cross_ema_up"]
            or flags["rsi_cross_wma_up"]
            or flags["ema_cross_wma_up"]
        ):
            continue

        event_names = []
        if flags["rsi_cross_ema_up"]:
            event_names.append("RSI↑EMA3")
        if flags["rsi_cross_wma_up"]:
            event_names.append("RSI↑WMA21")
        if flags["ema_cross_wma_up"]:
            event_names.append("EMA3↑WMA21")

        rows.append({
            "candle_start": bars[i]["start"].isoformat(),
            "candle_end": bars[i]["end"].isoformat(),
            "close": bars[i]["close"],
            "event": "+".join(event_names),
            "rsi9": r,
            "ema3_rsi": e,
            "wma21_rsi": w,
            "prev_rsi9": pr,
            "prev_ema3_rsi": pe,
            "prev_wma21_rsi": pw,
            **flags,
            "all_slopes_up": (
                flags["rsi_slope_up"]
                and flags["ema3_slope_up"]
                and flags["wma21_slope_up"]
            ),
        })

    print("\n=== BULLISH TRANSITION SEQUENCE TO VALIDATE ON CHART ===\n")
    if not rows:
        print("NO UPWARD TRANSITIONS FOUND")
    else:
        for n, row in enumerate(rows, 1):
            s = datetime.fromisoformat(row["candle_start"])
            e = datetime.fromisoformat(row["candle_end"])
            slopes = "/".join(
                "Y" if row[k] else "N"
                for k in ("rsi_slope_up", "ema3_slope_up", "wma21_slope_up")
            )
            print(
                f"{n:02d}. {s:%H:%M}-{e:%H:%M} "
                f"event={row['event']} close={row['close']:.2f} "
                f"RSI9={row['rsi9']:.4f} EMA3={row['ema3_rsi']:.4f} "
                f"WMA21={row['wma21_rsi']:.4f} slopes(R/E/W)={slopes}"
            )
            print(
                f"    prev RSI9={row['prev_rsi9']:.4f} "
                f"EMA3={row['prev_ema3_rsi']:.4f} WMA21={row['prev_wma21_rsi']:.4f}"
            )

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / f"bullish-transition-audit-{args.session_date}-v1-2.csv"
    json_path = outdir / f"bullish-transition-audit-{args.session_date}-v1-2.json"

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
                "purpose": "Descriptive audit of bullish upward transition sequence; no combined signal rule selected.",
                "events": [
                    "RSI9 crosses EMA3(RSI9) upward",
                    "RSI9 crosses WMA21(RSI9) upward",
                    "EMA3(RSI9) crosses WMA21(RSI9) upward",
                ],
                "transition_count": len(rows),
                "transitions": rows,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"\n5m bars={len(bars)} transition_candles={len(rows)}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print("No combined bullish timing window is imposed in V1.2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
