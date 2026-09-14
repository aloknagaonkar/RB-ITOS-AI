from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_ARCHETYPE_STUDY_V1_FIX2"
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


def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    """Yield every dict recursively so research artifacts need not expose `rows`."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def extract_economics_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Accept both flat `rows` schema and nested research artifacts.
    An economics row must identify the event and carry exact option entry fields.
    """
    out = []
    seen = set()
    for r in walk_dicts(doc):
        if not all(r.get(k) is not None for k in ("session_date", "setup_type", "direction")):
            continue
        if r.get("t3_state") != TARGET_STATE:
            continue
        if "entry_timestamp" not in r or "entry_price" not in r:
            continue
        sig = (
            str(r.get("block")),
            str(r.get("session_date")),
            str(r.get("setup_type")),
            str(r.get("direction")),
            str(r.get("entry_timestamp")),
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def extract_exit_rows(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not doc:
        return []
    out = []
    seen = set()
    for r in walk_dicts(doc):
        if r.get("policy_id") != FROZEN_POLICY:
            continue
        if not all(r.get(k) is not None for k in ("session_date", "direction", "entry_timestamp")):
            continue
        sig = (
            str(r.get("block")),
            str(r.get("session_date")),
            str(r.get("direction")),
            str(r.get("entry_timestamp")),
            str(r.get("policy_id")),
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def load_underlying(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    out = {}
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
                ts = parse_dt(raw)
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
    return sorted(out, key=lambda r: r["session_date"])


def resolve_t3_timestamp(state_row: dict[str, Any], econ_row: dict[str, Any] | None) -> str | None:
    for source in (state_row, econ_row or {}):
        v = source.get("t3_timestamp")
        if v:
            return str(v)

    # Exact economics entry is frozen as next-minute OPEN after T+3.
    # Therefore entry_timestamp - 1 minute is a deterministic reconstruction,
    # not a future/P&L inference.
    if econ_row and econ_row.get("entry_timestamp"):
        return (parse_dt(str(econ_row["entry_timestamp"])) - timedelta(minutes=1)).isoformat()

    return None


def directional_underlying_metrics(market, session_date: str, t3_timestamp: str | None):
    if not t3_timestamp:
        return {"available": False, "issue": "MISSING_T3_TIMESTAMP"}

    t3 = parse_dt(t3_timestamp)
    entry_ts = t3 + timedelta(minutes=1)
    entry_bar = market.get((session_date, entry_ts.isoformat()))
    if entry_bar is None:
        return {"available": False, "issue": "MISSING_ENTRY_BAR"}

    entry_open = float(entry_bar["open"])
    horizons = (5, 15, 30, 60)
    closes, favorable = {}, {}

    for m in horizons:
        ts = entry_ts + timedelta(minutes=m)
        bar = market.get((session_date, ts.isoformat()))
        if bar is None:
            closes[f"{m}m"] = None
            favorable[f"{m}m"] = None
        else:
            c = float(bar["close"])
            closes[f"{m}m"] = c
            favorable[f"{m}m"] = entry_open - c

    bars = []
    for m in range(61):
        ts = entry_ts + timedelta(minutes=m)
        bar = market.get((session_date, ts.isoformat()))
        if bar is not None:
            bars.append((m, bar))

    if not bars:
        return {"available": False, "issue": "NO_POST_ENTRY_BARS"}

    best_low = min(float(b["low"]) for _, b in bars)
    worst_high = max(float(b["high"]) for _, b in bars)
    best_close = min(float(b["close"]) for _, b in bars)
    worst_close = max(float(b["close"]) for _, b in bars)

    return {
        "available": True,
        "issue": None,
        "entry_timestamp": entry_ts.isoformat(),
        "entry_underlying_open": entry_open,
        "horizon_closes": closes,
        "favorable_close_points": favorable,
        "mfe_points_60m": entry_open - best_low,
        "mae_points_60m": worst_high - entry_open,
        "best_close_favorable_points_60m": entry_open - best_close,
        "worst_close_adverse_points_60m": worst_close - entry_open,
        "available_post_entry_bars_0_to_60": len(bars),
    }


def summarize(rows):
    valid = [r for r in rows if r["underlying"].get("available")]
    mfe = [r["underlying"]["mfe_points_60m"] for r in valid]

    def horizon_vals(h):
        return [
            r["underlying"]["favorable_close_points"][h]
            for r in valid
            if r["underlying"]["favorable_close_points"][h] is not None
        ]

    def avg(xs):
        return mean(xs) if xs else None

    return {
        "candidate_count": len(rows),
        "underlying_available_count": len(valid),
        "underlying_unavailable_count": len(rows) - len(valid),
        "underlying_issue_counts": dict(sorted(Counter(
            r["underlying"].get("issue") for r in rows if not r["underlying"].get("available")
        ).items())),
        "economics_joined_count": sum(r["option_economics"] is not None for r in rows),
        "frozen_exit_joined_count": sum(r["frozen_exit"] is not None for r in rows),
        "t1_oi_quality_counts": dict(sorted(Counter(r.get("t1_oi_quality") for r in rows).items())),
        "t3_oi_quality_counts": dict(sorted(Counter(r.get("t3_oi_quality") for r in rows).items())),
        "price_pass_count_counts": dict(sorted(Counter(r.get("price_pass_count") for r in rows).items())),
        "mean_mfe_points_60m": avg(mfe),
        "median_mfe_points_60m": median(mfe) if mfe else None,
        "mean_favorable_close_points_15m": avg(horizon_vals("15m")),
        "mean_favorable_close_points_30m": avg(horizon_vals("30m")),
        "mean_favorable_close_points_60m": avg(horizon_vals("60m")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--underlying", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--exit-research")
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

    market = load_underlying(Path(args.underlying))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    economics_rows = extract_economics_rows(economics)
    econ_idx = {event_key(r): r for r in economics_rows}

    exit_rows = extract_exit_rows(exit_doc)
    exit_idx = {}
    for r in exit_rows:
        # Exit-management rows do not always carry setup_type.
        # Join by date+direction+entry timestamp later.
        exit_idx[(str(r["session_date"]), str(r["direction"]), str(r["entry_timestamp"]))] = r

    rows = []
    for e in candidate_events(state, start, end):
        key = event_key(e)
        econ = econ_idx.get(key)
        score = e.get("t3_score") or {}
        t3_timestamp = resolve_t3_timestamp(e, econ)

        ex = None
        if econ and econ.get("entry_timestamp"):
            ex = exit_idx.get((
                str(e["session_date"]),
                str(e["direction"]),
                str(econ["entry_timestamp"]),
            ))

        if e.get("t3_timestamp"):
            t3_source = "STATE"
        elif econ and econ.get("t3_timestamp"):
            t3_source = "EXACT_OPTION_ECONOMICS_T3"
        elif econ and econ.get("entry_timestamp"):
            t3_source = "EXACT_OPTION_ECONOMICS_ENTRY_MINUS_1M"
        else:
            t3_source = "UNAVAILABLE"

        rows.append({
            "session_date": e["session_date"],
            "setup_type": e["setup_type"],
            "direction": e["direction"],
            "t3_timestamp": t3_timestamp,
            "t3_timestamp_source": t3_source,
            "t1_observation_state": (e.get("t1_observation") or {}).get("state"),
            "t1_oi_quality": (e.get("t1_observation") or {}).get("oi_quality"),
            "t3_oi_quality": score.get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get("exact_oi_transition_t1_to_t3"),
            "price_pass_ratio": score.get("price_pass_ratio"),
            "price_pass_count": score.get("price_pass_count"),
            "primary_outcome": e.get("primary_outcome"),
            "underlying": directional_underlying_metrics(
                market, e["session_date"], t3_timestamp
            ),
            "option_economics": None if econ is None else {
                "strike": econ.get("strike"),
                "instrument_key": econ.get("instrument_key"),
                "entry_timestamp": econ.get("entry_timestamp"),
                "entry_price": econ.get("entry_price"),
                "mfe_pct_15m": econ.get("mfe_pct_15m"),
                "mae_pct_15m": econ.get("mae_pct_15m"),
                "net_returns_pct": econ.get("net_returns_pct"),
                "oi_quality": econ.get("oi_quality"),
            },
            "frozen_exit": None if ex is None else {
                "policy_id": ex.get("policy_id"),
                "exit_timestamp": ex.get("exit_timestamp"),
                "exit_reason": ex.get("exit_reason"),
                "net_return_pct": ex.get("net_return_pct"),
            },
        })

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

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "source_discovery": {
            "economics_candidate_rows_found": len(economics_rows),
            "exit_policy_rows_found": len(exit_rows),
        },
        "selection_rule": {
            "setup_type": TARGET_SETUP,
            "direction": TARGET_DIRECTION,
            "t3_state": TARGET_STATE,
            "ranking_metric": "UNDERLYING_MFE_POINTS_60M",
            "option_pnl_used_for_candidate_selection": False,
            "retrospective_primary_outcome_used_for_candidate_selection": False,
        },
        "summary": summarize(ranked),
        "sep7_reference": next((r for r in ranked if r["session_date"] == "2026-09-07"), None),
        "ranked_rows": ranked,
        "integrity": {
            "frozen_v1_candidates_only": True,
            "ranking_uses_underlying_only": True,
            "option_pnl_used_only_descriptively": True,
            "oi_used_descriptively_not_as_posthoc_filter": True,
            "economics_rows_discovered_recursively": True,
            "t3_from_entry_minus_1m_allowed_only_because_frozen_entry_is_next_minute_open": True,
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
