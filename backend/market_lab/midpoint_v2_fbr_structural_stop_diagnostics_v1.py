from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_FBR_STRUCTURAL_STOP_DIAGNOSTICS_V1"
EXPECTED_STRUCTURAL_VERSION = "MIDPOINT_V2_STRUCTURAL_RECONSTRUCTION_V1"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V2_NEW_ARM_EXACT_OPTION_ECONOMICS_V1"
EXPECTED_ATTRIBUTION_VERSION = "MIDPOINT_V2_E15_STOP_REGIME_ATTRIBUTION_V1"

ARM = "FAILED_BREAK_RECLAIM"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}


def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def event_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("block")),
        str(row.get("session_date")),
        str(row.get("entry_arm") or (row.get("v2_result") or {}).get("entry_arm")),
        str(row.get("entry_direction") or (row.get("v2_result") or {}).get("entry_direction")),
    )


def parse_block_path(value: str) -> tuple[str, Path]:
    if "|" not in value:
        raise ValueError("expected BLOCK|path")
    block, path = value.split("|", 1)
    block = block.strip()
    if block not in ALLOWED_BLOCKS:
        raise ValueError(f"unsupported block {block!r}")
    return block, Path(path.strip())


def first_existing(headers: list[str], candidates: tuple[str, ...]) -> str:
    lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    raise ValueError(f"missing one of {candidates!r}; available={headers!r}")


def optional_existing(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
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
        close_col = first_existing(headers, ("close", "close_price", "c"))
        for row in rd:
            raw = row.get(ts_col)
            close = ffloat(row.get(close_col))
            if not raw or close is None:
                continue
            try:
                ts = parse_dt(str(raw))
            except ValueError:
                continue
            sd = str(row.get(date_col)) if date_col and row.get(date_col) else ts.date().isoformat()
            out[(sd, ts.isoformat())] = {"close": close}
    return out


def structural_invalidation(
    entry_direction: str,
    midpoint: float,
    close: float,
) -> bool:
    # Failed bearish break -> bullish reclaim: midpoint must remain reclaimed ABOVE.
    if entry_direction == "BULLISH":
        return close < midpoint
    # Failed bullish break -> bearish reclaim: midpoint must remain reclaimed BELOW.
    if entry_direction == "BEARISH":
        return close > midpoint
    raise ValueError(entry_direction)


def diagnose(
    structural_row: dict[str, Any],
    economics_row: dict[str, Any],
    attribution_row: dict[str, Any],
    underlying: dict[tuple[str, str], dict[str, float]],
) -> dict[str, Any]:
    sd = str(economics_row["session_date"])
    entry_ts = parse_dt(str(economics_row["entry_timestamp"]))
    direction = str(economics_row["entry_direction"])
    midpoint = float(structural_row["reference_midpoint"])

    invalidation_minute = None
    invalidation_timestamp = None
    invalidation_close = None
    closes = []

    for minute in range(0, 16):
        ts = entry_ts + timedelta(minutes=minute)
        bar = underlying.get((sd, ts.isoformat()))
        if bar is None:
            return {
                "block": economics_row["block"],
                "session_date": sd,
                "entry_direction": direction,
                "diagnostic_available": False,
                "issue": "MISSING_UNDERLYING_CLOSE",
                "missing_timestamp": ts.isoformat(),
            }
        close = float(bar["close"])
        closes.append({"minute": minute, "timestamp": ts.isoformat(), "close": close})
        if invalidation_minute is None and structural_invalidation(direction, midpoint, close):
            invalidation_minute = minute
            invalidation_timestamp = ts.isoformat()
            invalidation_close = close

    return {
        "block": economics_row["block"],
        "session_date": sd,
        "entry_arm": ARM,
        "original_direction": structural_row.get("direction"),
        "entry_direction": direction,
        "entry_timestamp": economics_row["entry_timestamp"],
        "reference_midpoint": midpoint,
        "structural_invalidation_rule": (
            "1M_CLOSE_BELOW_RECLAIMED_MIDPOINT"
            if direction == "BULLISH"
            else "1M_CLOSE_ABOVE_RECLAIMED_MIDPOINT"
        ),
        "diagnostic_available": True,
        "issue": None,
        "structural_invalidation_hit": invalidation_minute is not None,
        "structural_invalidation_minute": invalidation_minute,
        "structural_invalidation_timestamp": invalidation_timestamp,
        "structural_invalidation_close": invalidation_close,
        "e15_stop_regime": attribution_row.get("stop_regime"),
        "e15_net_return_pct": attribution_row.get("net_return_pct"),
        "initial_sl5_exit": attribution_row.get("stop_regime") == "INITIAL_SL5",
        "initial_sl5_recovered_to_entry": attribution_row.get("stop_path_recovered_to_entry"),
        "initial_sl5_reached_plus5": attribution_row.get("stop_path_reached_plus5"),
        "initial_sl5_final_15m_net_pct": attribution_row.get("stop_path_final_15m_net_pct"),
        "final_15m_net_pct": economics_row.get("net_returns_pct", {}).get("15m"),
        "underlying_closes": closes,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r.get("diagnostic_available")]
    initial = [r for r in valid if r.get("initial_sl5_exit")]
    rec = [r for r in initial if r.get("initial_sl5_recovered_to_entry")]
    nonrec = [r for r in initial if not r.get("initial_sl5_recovered_to_entry")]

    def hit_count(xs):
        return sum(bool(r.get("structural_invalidation_hit")) for r in xs)

    hit_minutes = [
        int(r["structural_invalidation_minute"])
        for r in valid
        if r.get("structural_invalidation_minute") is not None
    ]

    return {
        "trade_count": len(rows),
        "diagnostic_available_count": len(valid),
        "issue_counts": dict(sorted(Counter(str(r.get("issue")) for r in rows if r.get("issue")).items())),
        "structural_invalidation_hit_count": hit_count(valid),
        "median_structural_invalidation_minute": median(hit_minutes) if hit_minutes else None,
        "initial_sl5_count": len(initial),
        "initial_sl5_recovery_count": len(rec),
        "initial_sl5_nonrecovery_count": len(nonrec),
        "initial_sl5_recovery_with_structural_invalidation_count": hit_count(rec),
        "initial_sl5_recovery_without_structural_invalidation_count": len(rec) - hit_count(rec),
        "initial_sl5_nonrecovery_with_structural_invalidation_count": hit_count(nonrec),
        "initial_sl5_nonrecovery_without_structural_invalidation_count": len(nonrec) - hit_count(nonrec),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structural", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--attribution", required=True)
    ap.add_argument("--underlying", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    structural = load_json(Path(args.structural))
    economics = load_json(Path(args.economics))
    attribution = load_json(Path(args.attribution))

    if structural.get("research_version") != EXPECTED_STRUCTURAL_VERSION:
        raise SystemExit("unexpected structural version")
    if economics.get("research_version") != EXPECTED_ECONOMICS_VERSION:
        raise SystemExit("unexpected economics version")
    if attribution.get("research_version") != EXPECTED_ATTRIBUTION_VERSION:
        raise SystemExit("unexpected attribution version")

    if any((doc.get("integrity") or {}).get("oos_h_used") for doc in (economics, attribution)):
        raise SystemExit("OOS-H forbidden")

    specs = [parse_block_path(v) for v in args.underlying]
    if {b for b, _ in specs} != ALLOWED_BLOCKS:
        raise SystemExit("need underlying for TRAIN + OOS_A/B/C/D exactly")
    und = {b: load_underlying(p) for b, p in specs}

    sidx = {
        event_key(r): r
        for r in (structural.get("rows") or [])
        if (r.get("v2_result") or {}).get("entry_arm") == ARM
    }
    eidx = {
        event_key(r): r
        for r in (economics.get("rows") or [])
        if r.get("entry_arm") == ARM
    }
    aidx = {
        event_key(r): r
        for r in (attribution.get("rows") or [])
        if r.get("entry_arm") == ARM
    }

    if not (len(sidx) == len(eidx) == len(aidx) == 9):
        raise SystemExit(
            f"expected 9 FBR rows in each input, got structural={len(sidx)} "
            f"economics={len(eidx)} attribution={len(aidx)}"
        )

    rows = []
    for key, e in sorted(eidx.items()):
        if key not in sidx or key not in aidx:
            raise SystemExit(f"join mismatch for {key}")
        rows.append(diagnose(sidx[key], e, aidx[key], und[str(e["block"])]))

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "candidate_scope": "FAILED_BREAK_RECLAIM_ONLY",
        "candidate_count": len(rows),
        "hypothesis": {
            "type": "STRUCTURAL_INVALIDATION_DIAGNOSTIC",
            "rule": "FBR remains structurally valid while the reclaimed reference midpoint holds on 1-minute CLOSE",
            "bullish_fbr_invalidation": "1M_CLOSE_BELOW_REFERENCE_MIDPOINT",
            "bearish_fbr_invalidation": "1M_CLOSE_ABOVE_REFERENCE_MIDPOINT",
            "option_premium_stop_changed": False,
        },
        "overall_summary": summarize(rows),
        "direction_summaries": {
            d: summarize([r for r in rows if r["entry_direction"] == d])
            for d in ("BULLISH", "BEARISH")
        },
        "rows": rows,
        "integrity": {
            "fbr_only": True,
            "close_crossing_only": True,
            "wick_only_invalidation_used": False,
            "alternative_option_stop_thresholds_tested": False,
            "entry_logic_modified": False,
            "pnl_used_to_define_structural_level": False,
            "oos_h_used": False,
        },
        "governance": {
            "diagnostic_only": True,
            "no_structural_stop_promoted": True,
            "no_direction_filter_promoted": True,
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
