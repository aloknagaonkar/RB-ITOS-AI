from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_ARCHETYPE_STUDY_V1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"

DEFAULT_START = date(2026, 6, 9)
DEFAULT_END = date(2026, 9, 7)
TARGET_SETUP = "RED_BREAK"
TARGET_DIRECTION = "BEARISH"
TARGET_STATE = "CONFIRM_CONTINUATION"
FROZEN_POLICY = "SL5_BE5_TRAIL3_AFTER10_TIME15"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def first_existing(headers: list[str], names: tuple[str, ...]) -> str:
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    raise ValueError(f"missing one of {names}; available={headers}")


def optional_existing(headers: list[str], names: tuple[str, ...]) -> str | None:
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def ffloat(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_underlying(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    out: dict[tuple[str, str], dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        headers = list(rd.fieldnames or [])
        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts"))
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        open_col = first_existing(headers, ("open", "o"))
        high_col = first_existing(headers, ("high", "h"))
        low_col = first_existing(headers, ("low", "l"))
        close_col = first_existing(headers, ("close", "c"))
        for r in rd:
            raw = r.get(ts_col)
            if not raw:
                continue
            try:
                ts = parse_dt(str(raw))
            except ValueError:
                continue
            sd = str(r.get(date_col)) if date_col and r.get(date_col) else ts.date().isoformat()
            vals = {
                "open": ffloat(r.get(open_col)),
                "high": ffloat(r.get(high_col)),
                "low": ffloat(r.get(low_col)),
                "close": ffloat(r.get(close_col)),
            }
            if any(v is None for v in vals.values()):
                continue
            out[(sd, ts.isoformat())] = vals
    return out


def event_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("session_date")),
        str(row.get("setup_type")),
        str(row.get("direction")),
    )


def candidate_events(state: dict[str, Any], start: date, end: date) -> list[dict[str, Any]]:
    out = []
    for e in state.get("events") or []:
        sd = e.get("session_date")
        if not sd:
            continue
        d = date.fromisoformat(sd)
        if not (start <= d <= end):
            continue
        if e.get("setup_type") != TARGET_SETUP:
            continue
        if e.get("direction") != TARGET_DIRECTION:
            continue
        if e.get("t3_state") != TARGET_STATE:
            continue
        out.append(e)
    return sorted(out, key=lambda r: (r["session_date"], r.get("t3_timestamp") or ""))


def directional_underlying_metrics(
    market: dict[tuple[str, str], dict[str, float]],
    session_date: str,
    t3_timestamp: str,
) -> dict[str, Any]:
    t3 = parse_dt(t3_timestamp)
    entry_ts = t3 + timedelta(minutes=1)
    entry_bar = market.get((session_date, entry_ts.isoformat()))
    if entry_bar is None:
        return {"available": False, "issue": "MISSING_ENTRY_BAR"}

    entry_open = float(entry_bar["open"])
    horizons = (5, 15, 30, 60)
    closes: dict[str, float | None] = {}
    favorable_close_points: dict[str, float | None] = {}

    for m in horizons:
        ts = entry_ts + timedelta(minutes=m)
        bar = market.get((session_date, ts.isoformat()))
        if bar is None:
            closes[f"{m}m"] = None
            favorable_close_points[f"{m}m"] = None
        else:
            c = float(bar["close"])
            closes[f"{m}m"] = c
            favorable_close_points[f"{m}m"] = entry_open - c  # bearish favorable

    bars = []
    for m in range(0, 61):
        ts = entry_ts + timedelta(minutes=m)
        bar = market.get((session_date, ts.isoformat()))
        if bar is not None:
            bars.append((m, bar))

    if not bars:
        return {"available": False, "issue": "NO_POST_ENTRY_BARS"}

    best_low = min(float(b["low"]) for _, b in bars)
    worst_high = max(float(b["high"]) for _, b in bars)

    mfe_points_60m = entry_open - best_low
    mae_points_60m = worst_high - entry_open

    best_close = min(float(b["close"]) for _, b in bars)
    worst_close = max(float(b["close"]) for _, b in bars)

    return {
        "available": True,
        "issue": None,
        "entry_timestamp": entry_ts.isoformat(),
        "entry_underlying_open": entry_open,
        "horizon_closes": closes,
        "favorable_close_points": favorable_close_points,
        "mfe_points_60m": mfe_points_60m,
        "mae_points_60m": mae_points_60m,
        "best_close_favorable_points_60m": entry_open - best_close,
        "worst_close_adverse_points_60m": worst_close - entry_open,
        "available_post_entry_bars_0_to_60": len(bars),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r["underlying"].get("available")]
    mfe = [r["underlying"]["mfe_points_60m"] for r in valid]
    c15 = [
        r["underlying"]["favorable_close_points"]["15m"]
        for r in valid
        if r["underlying"]["favorable_close_points"]["15m"] is not None
    ]
    c30 = [
        r["underlying"]["favorable_close_points"]["30m"]
        for r in valid
        if r["underlying"]["favorable_close_points"]["30m"] is not None
    ]
    c60 = [
        r["underlying"]["favorable_close_points"]["60m"]
        for r in valid
        if r["underlying"]["favorable_close_points"]["60m"] is not None
    ]
    return {
        "candidate_count": len(rows),
        "underlying_available_count": len(valid),
        "t1_oi_quality_counts": dict(sorted(Counter(r.get("t1_oi_quality") for r in rows).items())),
        "t3_oi_quality_counts": dict(sorted(Counter(r.get("t3_oi_quality") for r in rows).items())),
        "price_pass_count_counts": dict(sorted(Counter(r.get("price_pass_count") for r in rows).items())),
        "mean_mfe_points_60m": mean(mfe) if mfe else None,
        "median_mfe_points_60m": median(mfe) if mfe else None,
        "mean_favorable_close_points_15m": mean(c15) if c15 else None,
        "mean_favorable_close_points_30m": mean(c30) if c30 else None,
        "mean_favorable_close_points_60m": mean(c60) if c60 else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--underlying", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--exit-research", required=False)
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    state = load_json(Path(args.state))
    economics = load_json(Path(args.economics))
    exit_doc = load_json(Path(args.exit_research)) if args.exit_research else None

    if state.get("research_version") != EXPECTED_STATE_VERSION:
        raise SystemExit(f"unexpected state version={state.get('research_version')!r}")
    if economics.get("research_version") != EXPECTED_ECONOMICS_VERSION:
        raise SystemExit(f"unexpected economics version={economics.get('research_version')!r}")

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    market = load_underlying(Path(args.underlying))

    econ_idx = {event_key(r): r for r in (economics.get("rows") or [])}

    exit_idx: dict[tuple[str, str, str], dict[str, Any]] = {}
    if exit_doc:
        for r in exit_doc.get("rows") or []:
            if r.get("policy_id") == FROZEN_POLICY:
                exit_idx[event_key(r)] = r

    rows = []
    for e in candidate_events(state, start, end):
        key = event_key(e)
        score = e.get("t3_score") or {}
        econ = econ_idx.get(key)
        ex = exit_idx.get(key)

        row = {
            "session_date": e["session_date"],
            "setup_type": e["setup_type"],
            "direction": e["direction"],
            "t3_timestamp": e.get("t3_timestamp"),
            "t1_observation_state": (e.get("t1_observation") or {}).get("state"),
            "t1_oi_quality": (e.get("t1_observation") or {}).get("oi_quality"),
            "t3_oi_quality": score.get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get("exact_oi_transition_t1_to_t3"),
            "price_pass_ratio": score.get("price_pass_ratio"),
            "price_pass_count": score.get("price_pass_count"),
            "primary_outcome": e.get("primary_outcome"),
            "underlying": directional_underlying_metrics(
                market, e["session_date"], e["t3_timestamp"]
            ),
            "option_economics": None,
            "frozen_exit": None,
        }

        if econ is not None:
            row["option_economics"] = {
                "strike": econ.get("strike"),
                "instrument_key": econ.get("instrument_key"),
                "entry_timestamp": econ.get("entry_timestamp"),
                "entry_price": econ.get("entry_price"),
                "mfe_pct_15m": econ.get("mfe_pct_15m"),
                "mae_pct_15m": econ.get("mae_pct_15m"),
                "net_returns_pct": econ.get("net_returns_pct"),
                "oi_quality": econ.get("oi_quality"),
            }

        if ex is not None:
            row["frozen_exit"] = {
                "policy_id": ex.get("policy_id"),
                "exit_timestamp": ex.get("exit_timestamp"),
                "exit_reason": ex.get("exit_reason"),
                "net_return_pct": ex.get("net_return_pct"),
            }

        rows.append(row)

    ranked = sorted(
        rows,
        key=lambda r: (
            r["underlying"].get("mfe_points_60m")
            if r["underlying"].get("mfe_points_60m") is not None
            else float("-inf")
        ),
        reverse=True,
    )

    for i, r in enumerate(ranked, 1):
        r["rank_by_underlying_mfe_60m"] = i

    sep7 = next((r for r in ranked if r["session_date"] == "2026-09-07"), None)

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "selection_rule": {
            "setup_type": TARGET_SETUP,
            "direction": TARGET_DIRECTION,
            "t3_state": TARGET_STATE,
            "ranking_metric": "UNDERLYING_MFE_POINTS_60M",
            "option_pnl_used_for_candidate_selection": False,
            "retrospective_primary_outcome_used_for_candidate_selection": False,
        },
        "summary": summarize(ranked),
        "sep7_reference": sep7,
        "ranked_rows": ranked,
        "integrity": {
            "frozen_v1_candidates_only": True,
            "ranking_uses_underlying_only": True,
            "option_pnl_used_only_descriptively": True,
            "oi_used_descriptively_not_as_posthoc_filter": True,
            "oos_h_used": False,
            "no_entry_rule_modified": True,
            "no_exit_rule_modified": True,
        },
        "governance": {
            "diagnostic_only": True,
            "no_new_filter_promoted": True,
            "no_exit_change_promoted": True,
            "fresh_oos_required_before_any_v2_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
