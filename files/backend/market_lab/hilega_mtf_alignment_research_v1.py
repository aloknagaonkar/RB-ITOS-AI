from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from .domain import IST
from .hilega_milega_historical_replay_v1 import UNDERLYING, load_or_fetch_1m
from .hilega_milega_strategy_v1 import HilegaMilegaIndicatorEngineV1, IndicatorSnapshot

MODEL = "HILEGA_MTF_ALIGNMENT_RESEARCH_V1"
ALIGNMENT_RULE = "FULL_STRUCTURE_ALIGNMENT_V1"

VERSIONS = {
    "V1_5M_ONLY": "Existing 5m directional entry; current 5m exit unchanged.",
    "V2_5M_10M": "Existing 5m trigger; require completed 10m full alignment.",
    "V3_5M_15M": "Existing 5m trigger; require completed 15m full alignment.",
    "V4_5M_10M_15M": "Existing 5m trigger; require completed 10m and 15m full alignment.",
    "V5_5M_HTF_NON_OPPOSITION": "Existing 5m trigger; completed 10m and 15m must not be opposite.",
}


@dataclass(frozen=True)
class TFBar:
    ts: datetime
    minutes: int
    open: float
    high: float
    low: float
    close: float

    @property
    def completed_at(self) -> datetime:
        return self.ts + timedelta(minutes=self.minutes)


@dataclass(frozen=True)
class TFSnapshot:
    bar: TFBar
    indicator: IndicatorSnapshot
    direction: str


class _CacheOnlyGateway:
    def historical_candles(self, instrument_key: str, session_date: date):
        raise RuntimeError(
            f"CACHE_ONLY_RESEARCH_MISSING_SOURCE:{instrument_key}:{session_date.isoformat()}"
        )


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"NAIVE_TIMESTAMP:{value}")
    return dt.astimezone(IST)


def _cache_dates(cache_root: Path) -> list[date]:
    out = []
    for p in cache_root.glob("*.json"):
        try:
            out.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return sorted(set(out))


def load_cached_1m(cache_root: Path, session_date: date):
    p = cache_root / f"{session_date.isoformat()}.json"
    if not p.is_file():
        return []
    return load_or_fetch_1m(
        _CacheOnlyGateway(),
        underlying=UNDERLYING,
        session_date=session_date,
        cache_root=cache_root,
        refresh_cache=False,
    )


def aggregate_exact_tf(candles, session_date: date, minutes: int) -> list[TFBar]:
    if minutes not in (5, 10, 15):
        raise ValueError("SUPPORTED_TIMEFRAMES_ARE_5_10_15")

    local = []
    for candle in candles:
        ts = candle.timestamp.astimezone(IST)
        if ts.date() != session_date:
            continue
        if ts.time() < time(9, 15) or ts.time() >= time(15, 30):
            continue
        local.append((ts, candle))
    local.sort(key=lambda x: x[0])

    by_ts = {ts: candle for ts, candle in local}
    start = datetime.combine(session_date, time(9, 15), tzinfo=IST)
    end = datetime.combine(session_date, time(15, 30), tzinfo=IST)

    result: list[TFBar] = []
    bucket = start
    while bucket + timedelta(minutes=minutes) <= end:
        expected = [bucket + timedelta(minutes=i) for i in range(minutes)]
        rows = [by_ts.get(ts) for ts in expected]
        if all(x is not None for x in rows):
            result.append(
                TFBar(
                    ts=bucket,
                    minutes=minutes,
                    open=float(rows[0].open),
                    high=max(float(x.high) for x in rows),
                    low=min(float(x.low) for x in rows),
                    close=float(rows[-1].close),
                )
            )
        bucket += timedelta(minutes=minutes)
    return result


def classify_alignment(ind: IndicatorSnapshot) -> str:
    if not ind.ready:
        return "UNREADY"
    r = float(ind.rsi9)
    e = float(ind.ema3_rsi)
    w = float(ind.wma21_rsi)
    if r > 50 and e > 50 and w > 50 and r > e > w:
        return "BULLISH"
    if r < 50 and e < 50 and w < 50 and r < e < w:
        return "BEARISH"
    return "NEUTRAL"


def latest_completed_snapshot(
    snapshots: list[TFSnapshot],
    decision_boundary: datetime,
) -> TFSnapshot | None:
    candidates = [s for s in snapshots if s.bar.completed_at <= decision_boundary]
    return candidates[-1] if candidates else None


def _snapshot_payload(s: TFSnapshot | None) -> dict[str, Any]:
    if s is None:
        return {
            "bar_timestamp": None,
            "completed_at": None,
            "direction": "UNAVAILABLE",
            "rsi9": None,
            "ema3_rsi": None,
            "wma21_rsi": None,
        }
    return {
        "bar_timestamp": s.bar.ts.isoformat(),
        "completed_at": s.bar.completed_at.isoformat(),
        "direction": s.direction,
        "rsi9": s.indicator.rsi9,
        "ema3_rsi": s.indicator.ema3_rsi,
        "wma21_rsi": s.indicator.wma21_rsi,
    }


def _passes(version: str, direction: str, s10: TFSnapshot | None, s15: TFSnapshot | None) -> bool:
    d10 = s10.direction if s10 else "UNAVAILABLE"
    d15 = s15.direction if s15 else "UNAVAILABLE"
    opposite = "BEARISH" if direction == "BULLISH" else "BULLISH"

    if version == "V1_5M_ONLY":
        return True
    if version == "V2_5M_10M":
        return d10 == direction
    if version == "V3_5M_15M":
        return d15 == direction
    if version == "V4_5M_10M_15M":
        return d10 == direction and d15 == direction
    if version == "V5_5M_HTF_NON_OPPOSITION":
        return d10 not in ("UNAVAILABLE", opposite) and d15 not in ("UNAVAILABLE", opposite)
    raise KeyError(version)


def _points(direction: str, entry: float, exit_: float) -> float:
    return (exit_ - entry) if direction == "BULLISH" else (entry - exit_)


def _mfe_mae(direction: str, entry: float, bars: list[TFBar]) -> tuple[float | None, float | None]:
    if not bars:
        return None, None
    high = max(x.high for x in bars)
    low = min(x.low for x in bars)
    if direction == "BULLISH":
        return high - entry, low - entry
    return entry - low, entry - high


def _read_trades(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"BASELINE_DIRECTIONAL_TRADES_MISSING:{path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build_mtf_snapshots(
    *,
    cache_root: Path,
    target_dates: list[date],
    warmup_calendar_days: int = 45,
) -> tuple[dict[date, dict[int, list[TFSnapshot]]], dict[date, list[TFBar]], dict[str, Any]]:
    if not target_dates:
        raise ValueError("NO_TARGET_DATES")

    available = _cache_dates(cache_root)
    begin = min(target_dates) - timedelta(days=warmup_calendar_days)
    end = max(target_dates)
    use_dates = [d for d in available if begin <= d <= end]

    engines = {
        5: HilegaMilegaIndicatorEngineV1(),
        10: HilegaMilegaIndicatorEngineV1(),
        15: HilegaMilegaIndicatorEngineV1(),
    }

    snapshots: dict[date, dict[int, list[TFSnapshot]]] = {
        d: {5: [], 10: [], 15: []} for d in target_dates
    }
    five_bars: dict[date, list[TFBar]] = {d: [] for d in target_dates}
    loaded: dict[str, int] = {}

    for d in use_dates:
        candles = load_cached_1m(cache_root, d)
        loaded[d.isoformat()] = len(candles)
        if not candles:
            continue
        for tf in (5, 10, 15):
            bars = aggregate_exact_tf(candles, d, tf)
            for bar in bars:
                ind = engines[tf].update(bar.close)
                if d in snapshots:
                    snap = TFSnapshot(bar=bar, indicator=ind, direction=classify_alignment(ind))
                    snapshots[d][tf].append(snap)
                    if tf == 5:
                        five_bars[d].append(bar)

    manifest = {
        "warmup_begin": begin.isoformat(),
        "target_begin": min(target_dates).isoformat(),
        "target_end": max(target_dates).isoformat(),
        "warmup_calendar_days": warmup_calendar_days,
        "cache_dates_considered": [d.isoformat() for d in use_dates],
        "source_1m_counts": loaded,
    }
    return snapshots, five_bars, manifest


def run_research(
    *,
    dates: list[date],
    cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
    replay_root: str | Path = "data/historical-evidence/hilega-directional-replay-v1",
    output_root: str | Path = "data/historical-evidence/hilega-mtf-alignment-research-v1/14-session-v1",
    warmup_calendar_days: int = 45,
) -> dict[str, Any]:
    dates = sorted(set(dates))
    cache_root = Path(cache_root)
    replay_root = Path(replay_root)
    output_root = Path(output_root)

    snaps, five_bars, source_manifest = build_mtf_snapshots(
        cache_root=cache_root,
        target_dates=dates,
        warmup_calendar_days=warmup_calendar_days,
    )

    detail: list[dict[str, Any]] = []
    baseline_trade_count = 0

    for d in dates:
        trade_path = replay_root / d.isoformat() / "directional-trades.csv"
        trades = _read_trades(trade_path)
        baseline_trade_count += len(trades)

        five_by_ts = {b.ts: b for b in five_bars[d]}

        for trade_index, trade in enumerate(trades, start=1):
            direction = trade["direction"]
            baseline_entry_ts = _parse_dt(trade["entry_time"])
            exit_ts = _parse_dt(trade["exit_time"])
            baseline_entry_price = float(trade["entry_price"])
            exit_price = float(trade["exit_price"])

            candidates = [
                b for b in five_bars[d]
                if baseline_entry_ts <= b.ts < exit_ts
            ]

            for version in VERSIONS:
                selected = None
                selected10 = None
                selected15 = None

                for b in candidates:
                    boundary = b.completed_at
                    s10 = latest_completed_snapshot(snaps[d][10], boundary)
                    s15 = latest_completed_snapshot(snaps[d][15], boundary)
                    if _passes(version, direction, s10, s15):
                        selected = b
                        selected10 = s10
                        selected15 = s15
                        break

                row: dict[str, Any] = {
                    "model": MODEL,
                    "alignment_rule": ALIGNMENT_RULE,
                    "session_date": d.isoformat(),
                    "trade_index": trade_index,
                    "direction": direction,
                    "route_event": trade.get("entry_event"),
                    "version": version,
                    "baseline_entry_time": baseline_entry_ts.isoformat(),
                    "baseline_entry_price": baseline_entry_price,
                    "baseline_exit_time": exit_ts.isoformat(),
                    "baseline_exit_price": exit_price,
                    "baseline_points": float(trade["points"]),
                }

                if selected is None:
                    row.update({
                        "accepted": False,
                        "entry_time": None,
                        "entry_boundary": None,
                        "entry_price": None,
                        "entry_delay_minutes": None,
                        "exit_time": exit_ts.isoformat(),
                        "exit_price": exit_price,
                        "points": None,
                        "outcome": "FILTERED",
                        "mfe_points": None,
                        "mae_points": None,
                    })
                    # Snapshot the HTF state at the original 5m decision boundary for diagnosis.
                    original5 = five_by_ts.get(baseline_entry_ts)
                    original_boundary = (
                        original5.completed_at if original5 else baseline_entry_ts + timedelta(minutes=5)
                    )
                    selected10 = latest_completed_snapshot(snaps[d][10], original_boundary)
                    selected15 = latest_completed_snapshot(snaps[d][15], original_boundary)
                else:
                    entry_price = baseline_entry_price if version == "V1_5M_ONLY" else selected.close
                    pts = _points(direction, entry_price, exit_price)
                    path_bars = [b for b in five_bars[d] if selected.ts <= b.ts <= exit_ts]
                    mfe, mae = _mfe_mae(direction, entry_price, path_bars)
                    row.update({
                        "accepted": True,
                        "entry_time": selected.ts.isoformat(),
                        "entry_boundary": selected.completed_at.isoformat(),
                        "entry_price": round(entry_price, 6),
                        "entry_delay_minutes": int((selected.ts - baseline_entry_ts).total_seconds() // 60),
                        "exit_time": exit_ts.isoformat(),
                        "exit_price": exit_price,
                        "points": round(pts, 6),
                        "outcome": "WIN" if pts > 0 else ("LOSS" if pts < 0 else "FLAT"),
                        "mfe_points": None if mfe is None else round(mfe, 6),
                        "mae_points": None if mae is None else round(mae, 6),
                    })

                p10 = _snapshot_payload(selected10)
                p15 = _snapshot_payload(selected15)
                for k, v in p10.items():
                    row[f"tf10_{k}"] = v
                for k, v in p15.items():
                    row[f"tf15_{k}"] = v
                detail.append(row)

    summaries = []
    for version in VERSIONS:
        rows = [r for r in detail if r["version"] == version]
        accepted = [r for r in rows if r["accepted"]]
        filtered = [r for r in rows if not r["accepted"]]
        points = [float(r["points"]) for r in accepted]
        delays = [int(r["entry_delay_minutes"]) for r in accepted if r["entry_delay_minutes"] is not None]
        summaries.append({
            "version": version,
            "description": VERSIONS[version],
            "baseline_opportunities": len(rows),
            "accepted_trades": len(accepted),
            "filtered_trades": len(filtered),
            "wins": sum(1 for r in accepted if r["outcome"] == "WIN"),
            "losses": sum(1 for r in accepted if r["outcome"] == "LOSS"),
            "flat": sum(1 for r in accepted if r["outcome"] == "FLAT"),
            "net_points": round(sum(points), 6),
            "avg_points": round(sum(points) / len(points), 6) if points else None,
            "avg_entry_delay_minutes": round(sum(delays) / len(delays), 3) if delays else None,
            "max_entry_delay_minutes": max(delays) if delays else None,
            "avg_mfe_points": round(
                sum(float(r["mfe_points"]) for r in accepted if r["mfe_points"] is not None)
                / max(1, sum(1 for r in accepted if r["mfe_points"] is not None)), 6
            ) if accepted else None,
            "avg_mae_points": round(
                sum(float(r["mae_points"]) for r in accepted if r["mae_points"] is not None)
                / max(1, sum(1 for r in accepted if r["mae_points"] is not None)), 6
            ) if accepted else None,
        })

    # Direction splits help avoid hiding bullish/bearish asymmetry.
    by_direction = []
    for version in VERSIONS:
        for direction in ("BULLISH", "BEARISH"):
            rows = [r for r in detail if r["version"] == version and r["direction"] == direction]
            accepted = [r for r in rows if r["accepted"]]
            by_direction.append({
                "version": version,
                "direction": direction,
                "baseline_opportunities": len(rows),
                "accepted_trades": len(accepted),
                "filtered_trades": len(rows) - len(accepted),
                "wins": sum(1 for r in accepted if r["outcome"] == "WIN"),
                "losses": sum(1 for r in accepted if r["outcome"] == "LOSS"),
                "net_points": round(sum(float(r["points"]) for r in accepted), 6),
            })

    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(output_root / "mtf-trade-comparison.csv", detail)
    (output_root / "mtf-trade-comparison.json").write_text(
        json.dumps(detail, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_csv(output_root / "mtf-version-summary.csv", summaries)
    (output_root / "mtf-version-summary.json").write_text(
        json.dumps(summaries, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_csv(output_root / "mtf-by-direction.csv", by_direction)

    manifest = {
        "model": MODEL,
        "status": "PASS",
        "research_only": True,
        "live_strategy_changed": False,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "alignment_rule": ALIGNMENT_RULE,
        "alignment_definition": {
            "BULLISH": "RSI9>50, EMA3(RSI)>50, WMA21(RSI)>50, RSI9>EMA3>WMA21",
            "BEARISH": "RSI9<50, EMA3(RSI)<50, WMA21(RSI)<50, RSI9<EMA3<WMA21",
            "NEUTRAL": "ready but neither full bullish nor full bearish structure",
            "UNREADY": "indicator chain not fully ready",
        },
        "causality": "Only HTF bars with completed_at <= 5m decision boundary are visible.",
        "exit_policy": "Existing baseline 5m exit time/price unchanged for all variants.",
        "dates": [d.isoformat() for d in dates],
        "sessions": len(dates),
        "baseline_trade_count": baseline_trade_count,
        "versions": VERSIONS,
        "source": source_manifest,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )

    return {
        "model": MODEL,
        "status": "PASS",
        "research_only": True,
        "sessions": len(dates),
        "baseline_trade_count": baseline_trade_count,
        "output_root": str(output_root),
        "summary": summaries,
    }
