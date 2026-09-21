from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any

MODEL = "HILEGA_MILEGA_BULLISH_TODAY_V1"


def load_session(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sessions = doc.get("sessions") or []
    if len(sessions) != 1:
        raise ValueError(f"{path}: expected exactly one session, found {len(sessions)}")
    s = sessions[0]
    if s.get("status") != "AVAILABLE":
        raise ValueError(f"{path}: status={s.get('status')!r}, expected AVAILABLE")
    return s


def minute_spot_index(session: dict[str, Any]) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for r in session.get("rows") or []:
        if r.get("spot") is None:
            continue
        ts = datetime.fromisoformat(str(r["timestamp"])).replace(second=0, microsecond=0)
        # rows repeat by strike; spot should be identical, so keep first exact minute.
        out.setdefault(ts, float(r["spot"]))
    return out


def build_5m_closes(spots: dict[datetime, float]) -> list[tuple[datetime, float]]:
    """Return exact 5m candle END checkpoints: 09:20, 09:25, ... 15:30 when present."""
    if not spots:
        return []
    ds = min(spots).date()
    tz = min(spots).tzinfo
    t = datetime.combine(ds, time(9, 20), tzinfo=tz)
    end = datetime.combine(ds, time(15, 30), tzinfo=tz)
    out: list[tuple[datetime, float]] = []
    while t <= end:
        if t in spots:
            out.append((t, spots[t]))
        t += timedelta(minutes=5)
    return out


def rma(values: list[float], length: int) -> list[float | None]:
    """TradingView/Pine-style Wilder RMA: SMA seed, then alpha=1/length."""
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    seed = sum(values[:length]) / length
    out[length - 1] = seed
    prev = seed
    alpha = 1.0 / length
    for i in range(length, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def pine_rsi(values: list[float], length: int = 9) -> list[float | None]:
    if not values:
        return []
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = rma(gains[1:], length)
    avg_loss = rma(losses[1:], length)
    out: list[float | None] = [None] * len(values)
    # avg arrays correspond to price indices 1..end; first valid RSI at index length.
    for price_i in range(length, len(values)):
        g = avg_gain[price_i - 1]
        l = avg_loss[price_i - 1]
        if g is None or l is None:
            continue
        if l == 0:
            out[price_i] = 100.0
        elif g == 0:
            out[price_i] = 0.0
        else:
            rs = g / l
            out[price_i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def ema_optional(values: list[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    alpha = 2.0 / (length + 1.0)
    prev: float | None = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            prev = float(v)
        else:
            prev = alpha * float(v) + (1.0 - alpha) * prev
        out[i] = prev
    return out


def wma_optional(values: list[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    denom = length * (length + 1) / 2.0
    for i in range(len(values)):
        if i + 1 < length:
            continue
        win = values[i - length + 1 : i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum((j + 1) * float(v) for j, v in enumerate(win)) / denom
    return out


def detect_signals(
    series: list[tuple[datetime, float]],
    target_date: str,
) -> list[dict[str, Any]]:
    times = [t for t, _ in series]
    closes = [x for _, x in series]
    rsi = pine_rsi(closes, 9)
    e3 = ema_optional(rsi, 3)
    w21 = wma_optional(rsi, 21)
    rows: list[dict[str, Any]] = []
    for i in range(1, len(series)):
        if times[i].date().isoformat() != target_date:
            continue
        vals = (rsi[i-1], e3[i-1], w21[i-1], rsi[i], e3[i], w21[i])
        if any(v is None for v in vals):
            continue
        prev_rsi, prev_e3, prev_w21, cur_rsi, cur_e3, cur_w21 = [float(v) for v in vals]
        rsi_crosses_above_ema3 = prev_rsi <= prev_e3 and cur_rsi > cur_e3
        both_above_wma21 = cur_rsi > cur_w21 and cur_e3 > cur_w21
        if not (rsi_crosses_above_ema3 and both_above_wma21):
            continue
        end = times[i]
        start = end - timedelta(minutes=5)
        rows.append({
            "session_date": target_date,
            "candle_start": start.isoformat(),
            "candle_end": end.isoformat(),
            "close": closes[i],
            "rsi9": cur_rsi,
            "ema3_rsi": cur_e3,
            "wma21_rsi": cur_w21,
            "prev_rsi9": prev_rsi,
            "prev_ema3_rsi": prev_e3,
            "prev_wma21_rsi": prev_w21,
            "rsi_crossed_above_ema3": True,
            "rsi_above_wma21": cur_rsi > cur_w21,
            "ema3_above_wma21": cur_e3 > cur_w21,
        })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-date", default="2026-09-21")
    ap.add_argument("--positioning", default=None,
                    help="Exact target-day positioning.json. Defaults under historical-oi-build/<date>/positioning.json")
    ap.add_argument("--warmup-positioning", action="append", default=[],
                    help="Optional prior-session positioning.json; repeat for multiple files, oldest first. Recommended for TradingView-exact morning signals.")
    ap.add_argument("--positioning-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--output-dir", default="data/historical-evidence/branch-c-hilega-milega-bullish-today-v1")
    args = ap.parse_args()

    target_path = Path(args.positioning) if args.positioning else Path(args.positioning_root) / args.session_date / "positioning.json"
    if not target_path.exists():
        raise SystemExit(
            f"Target positioning file not found: {target_path}\n"
            f"Pass it explicitly with --positioning /path/to/positioning.json"
        )

    all_series: list[tuple[datetime, float]] = []
    warmup_files = [Path(p) for p in args.warmup_positioning]
    for p in warmup_files + [target_path]:
        session = load_session(p)
        all_series.extend(build_5m_closes(minute_spot_index(session)))
    all_series.sort(key=lambda x: x[0])

    # Remove accidental duplicate checkpoints while preserving latest supplied source.
    dedup: dict[datetime, float] = {}
    for t, c in all_series:
        dedup[t] = c
    series = sorted(dedup.items())

    signals = detect_signals(series, args.session_date)
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "bullish-signals-today-v1.csv", signals)

    summary = {
        "model": MODEL,
        "session_date": args.session_date,
        "rule": "RSI9 crosses above EMA3(RSI9) AND RSI9 > WMA21(RSI9) AND EMA3(RSI9) > WMA21(RSI9)",
        "target_positioning": str(target_path),
        "warmup_files": [str(p) for p in warmup_files],
        "warmup_mode": "PRIOR_SESSION_INCLUDED" if warmup_files else "SAME_SESSION_ONLY",
        "signal_count": len(signals),
        "signals": signals,
    }
    (out / "bullish-signals-today-v1.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"model={MODEL} session={args.session_date} signals={len(signals)} warmup={'PRIOR_SESSION_INCLUDED' if warmup_files else 'SAME_SESSION_ONLY'}")
    print("RULE: RSI9 crosses ABOVE EMA3(RSI9), with RSI9 and EMA3(RSI9) both ABOVE WMA21(RSI9)")
    if not warmup_files:
        print("WARNING: no prior-session warmup supplied. Morning TradingView values may differ; only signals after same-session indicator warmup are testable.")
    print("\n=== BULLISH CANDLE TIMINGS TO VALIDATE ON CHART ===")
    if not signals:
        print("NO_MATCHING_BULLISH_CANDLES")
    for n, r in enumerate(signals, 1):
        s = datetime.fromisoformat(r["candle_start"]).strftime("%H:%M")
        e = datetime.fromisoformat(r["candle_end"]).strftime("%H:%M")
        print(
            f"{n:02d}. {s}->{e}  close={r['close']:.2f}  "
            f"RSI9={r['rsi9']:.2f} EMA3={r['ema3_rsi']:.2f} WMA21={r['wma21_rsi']:.2f}"
        )
    print(f"CSV: {out/'bullish-signals-today-v1.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
