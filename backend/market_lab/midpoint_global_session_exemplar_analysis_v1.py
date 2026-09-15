from __future__ import annotations

"""
MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1

Purpose
-------
Analyze the complete development universe across TRAIN + OOS_A/B/C/D:
- 99 historical sessions
- 184 leakage-safe structural events
- both BULLISH and BEARISH families
- compare strong winners, weak winners, losers, and rejected/missed setups
- use Sep-07 as a historical exemplar and allow Sep-15 current-day as an optional external reference

This study is descriptive only:
- no rule changes
- no threshold tuning
- no promotion
- no OOS E/F/G/H
- no order emission
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}
HORIZONS = (1, 3, 5, 10, 15)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def pick(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def pct_change(a: float | None, b: float | None) -> float | None:
    if a in (None, 0) or b is None:
        return None
    return ((b / a) - 1.0) * 100.0


def metric(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0, "positive_count": 0, "win_rate_pct": None,
            "mean_pct": None, "median_pct": None, "sum_pct_points": None,
            "profit_factor": None,
        }
    pos = [x for x in values if x > 0]
    neg = [x for x in values if x < 0]
    gp = sum(pos)
    gl = abs(sum(neg))
    return {
        "count": len(values),
        "positive_count": len(pos),
        "win_rate_pct": 100.0 * len(pos) / len(values),
        "mean_pct": mean(values),
        "median_pct": median(values),
        "sum_pct_points": sum(values),
        "profit_factor": (gp / gl if gl else None),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "count": len(rows),
        "direction_counts": dict(Counter(r.get("direction") for r in rows)),
        "decision_counts": dict(Counter(r.get("decision_family") for r in rows)),
    }
    for h in HORIZONS:
        vals = [
            float((r.get("option_economics") or {}).get(f"net_{h}m_pct"))
            for r in rows
            if (r.get("option_economics") or {}).get(f"net_{h}m_pct") is not None
        ]
        out[f"net_{h}m"] = metric(vals)
    return out


def load_structural_events(doc: dict[str, Any]) -> list[dict[str, Any]]:
    # Canonical MIDPOINT_V2_STRUCTURAL_RECONSTRUCTION_V1 stores its
    # 184 reconstructed structural events in top-level `rows`, not `events`.
    # Keep `events` as a compatibility fallback for future/alternate artifacts.
    events = doc.get("rows")
    source_key = "rows"
    if not isinstance(events, list):
        events = doc.get("events")
        source_key = "events"
    if not isinstance(events, list):
        raise ValueError(
            "structural reconstruction missing top-level rows/events list; "
            f"keys={sorted(doc.keys())}"
        )

    out = []
    for e in events:
        if not isinstance(e, dict):
            continue
        block = str(e.get("block") or "")
        if block in FORBIDDEN_BLOCKS:
            continue
        if block not in ALLOWED_BLOCKS:
            continue
        session = str(e.get("session_date") or "")
        if not session:
            continue

        # `direction` is the original structural direction.  For new V2 arms,
        # v2_result.entry_direction may differ (failed-break reclaim). Preserve
        # both and use original direction for the global structural population.
        direction = str(e.get("direction") or "")
        if direction not in {"BULLISH", "BEARISH"}:
            continue

        row = dict(e)
        row["_structural_source_key"] = source_key
        out.append(row)

    expected = doc.get("structural_event_count")
    if expected is not None and len(out) != int(expected):
        raise ValueError(
            f"structural population mismatch: loaded={len(out)} "
            f"expected structural_event_count={expected}"
        )
    return out


def stable_feature_index(doc: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for e in doc.get("events", []):
        if not isinstance(e, dict):
            continue
        block = str(e.get("block") or "")
        session = str(e.get("session_date") or "")
        setup = str(e.get("setup_type") or "")
        if block in ALLOWED_BLOCKS and session and setup:
            out[(block, session, setup)] = e
    return out


def arm_c_trade_index(doc: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows = doc.get("arm_c_trades")
    if not isinstance(rows, list):
        raise ValueError("controlled comparison missing top-level arm_c_trades")
    out = {}
    for r in rows:
        block = str(r.get("block") or "")
        session = str(r.get("session_date") or "")
        direction = str(r.get("direction") or "")
        signal = str(r.get("signal_timestamp") or "")
        if block in ALLOWED_BLOCKS and session and direction and signal:
            out[(block, session, signal)] = r
    return out


def all_option_trade_index(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("trades")
    return rows if isinstance(rows, list) else []


def load_positioning(items: list[tuple[str, Path]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for block, path in items:
        if block not in ALLOWED_BLOCKS:
            raise ValueError(block)
        for r in load_csv(path):
            ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
            if not ts:
                continue
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            if ts.minute % 5 != 0 or ts.second != 0:
                continue
            off = num(pick(r, "strike_offset", "offset"))
            if off is not None and abs(off) > 1e-9:
                continue
            out[(block, session, ts.isoformat())] = {
                "moving_atm": num(pick(r, "moving_atm", "atm", "atm_strike", "strike")),
                "ce_state": str(pick(r, "ce_5m_state", "ce_state") or ""),
                "pe_state": str(pick(r, "pe_5m_state", "pe_state") or ""),
                "ce_premium": num(pick(r, "ce_premium", "ce_price")),
                "ce_oi": num(pick(r, "ce_oi")),
                "pe_premium": num(pick(r, "pe_premium", "pe_price")),
                "pe_oi": num(pick(r, "pe_oi")),
            }
    return out


def load_futures(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for r in load_csv(path):
        ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
        if not ts:
            continue
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        out[(session, ts.isoformat())] = {
            "futures_close": num(pick(r, "futures_close", "close")),
            "futures_vwap": num(pick(r, "futures_vwap", "session_vwap", "vwap")),
        }
    return out


def latest_completed_5m(ts: datetime) -> datetime:
    minute = (ts.minute // 5) * 5
    return ts.replace(minute=minute, second=0, microsecond=0)


def decision_family(e: dict[str, Any]) -> str:
    t3 = str(e.get("t3_state") or "")
    v2 = e.get("v2_result") if isinstance(e.get("v2_result"), dict) else {}
    final = str(
        v2.get("final_state")
        or e.get("v2_final_state")
        or e.get("final_state")
        or ""
    )
    arm = str(v2.get("entry_arm") or e.get("entry_arm") or "")

    if arm == "BASE_THEN_GO" or final == "CONFIRM_BASE_THEN_GO":
        return "BASE_THEN_GO"
    if arm == "FAILED_BREAK_RECLAIM" or final == "CONFIRM_FAILED_BREAK_RECLAIM":
        return "FAILED_BREAK_RECLAIM"
    if arm == "IMMEDIATE_CONTINUATION" or t3 == "CONFIRM_CONTINUATION" or final == "CONFIRM_CONTINUATION":
        return "IMMEDIATE_CONTINUATION"
    if "CANCEL" in t3 or "CANCEL" in final:
        return "CANCEL"
    if "RECLAIM" in t3 or "RECLAIM" in final:
        return "RECLAIM"
    if "WAIT" in t3 or "WAIT" in final or "BASE_WATCH" in final:
        return "WAIT"
    return final or t3 or "OTHER"


def extract_features(
    e: dict[str, Any],
    stable: dict[str, Any] | None,
    positioning: dict[tuple[str, str, str], dict[str, Any]],
    futures: dict[tuple[str, str], dict[str, Any]],
    diag_idx: dict[tuple[str, str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    block = str(e.get("block"))
    session = str(e.get("session_date"))
    setup = str(e.get("setup_type") or "")
    direction = str(e.get("direction"))
    v2 = e.get("v2_result") if isinstance(e.get("v2_result"), dict) else {}

    # For global comparison, T3 is the common decision-time anchor for all 184
    # structural events. Later V2 confirmation remains recorded separately.
    t3_raw = e.get("t3_timestamp") or (stable or {}).get("t3_timestamp")
    t3_ts = parse_ts(t3_raw)
    confirmation_raw = e.get("confirmation_timestamp") or v2.get("confirmation_timestamp")
    confirmation_ts = parse_ts(confirmation_raw)

    cp = latest_completed_5m(t3_ts) if t3_ts else None
    p = positioning.get((block, session, cp.isoformat())) if cp else None
    f = futures.get((session, cp.isoformat())) if cp else None

    t3_score = (stable or {}).get("t3_score") or e.get("t3_score") or {}
    price_features = actual_t3_features(
        block, session, setup,
        t3_ts.isoformat() if t3_ts else None,
        diag_idx,
    )

    fv_dist = None
    fv_pct = None
    aligned = None
    if f and f.get("futures_close") is not None and f.get("futures_vwap") is not None:
        fc = float(f["futures_close"])
        vw = float(f["futures_vwap"])
        fv_dist = fc - vw
        fv_pct = (fv_dist / vw) * 100.0 if vw else None
        aligned = (
            direction == "BULLISH" and fc > vw
        ) or (
            direction == "BEARISH" and fc < vw
        )

    return {
        "t3_timestamp": t3_ts.isoformat() if t3_ts else None,
        "signal_timestamp": (
            confirmation_ts.isoformat()
            if confirmation_ts
            else (t3_ts.isoformat() if t3_ts else None)
        ),
        "v2_confirmation_timestamp": confirmation_ts.isoformat() if confirmation_ts else None,
        "oi_vwap_checkpoint_timestamp": cp.isoformat() if cp else None,
        "price_features": price_features,
        "price_features_available_count": len(price_features),
        "price_pass_count": t3_score.get("price_pass_count"),
        "price_pass_ratio": t3_score.get("price_pass_ratio"),
        "feature_passes": t3_score.get("feature_passes"),
        "oi_quality": str((stable or {}).get("oi_quality") or t3_score.get("oi_quality") or ""),
        "exact_oi_transition_t1_to_t3": (
            (stable or {}).get("exact_oi_transition_t1_to_t3")
            or e.get("exact_oi_transition_t1_to_t3")
        ),
        "oi": p,
        "futures": {
            **(f or {}),
            "distance_points": fv_dist,
            "distance_pct": fv_pct,
            "aligned": aligned,
        } if f else None,
    }

def attach_option_economics(
    row: dict[str, Any],
    arm_c_idx: dict[tuple[str, str, str], dict[str, Any]],
    all_option_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    signal = row.get("signal_timestamp")
    block = row["block"]
    session = row["session_date"]
    direction = row["direction"]

    tr = None
    if signal:
        tr = arm_c_idx.get((block, session, signal))

    if tr is None:
        # descriptive fallback: exact same block/session/direction from canonical option economics
        candidates = [
            x for x in all_option_rows
            if str(x.get("block")) == block
            and str(x.get("session_date")) == session
            and str(x.get("direction")) == direction
        ]
        if len(candidates) == 1:
            tr = candidates[0]

    if tr is None:
        return {**row, "option_economics": None}

    nr = tr.get("net_returns_pct") or {}
    return {
        **row,
        "option_economics": {
            "option_side": tr.get("option_side"),
            "strike": tr.get("strike"),
            "instrument_key": tr.get("instrument_key"),
            "entry_timestamp": tr.get("entry_timestamp"),
            "entry_price": tr.get("entry_price"),
            **{f"net_{h}m_pct": nr.get(f"{h}m") for h in HORIZONS},
            "mfe_pct_15m": tr.get("mfe_pct_15m"),
            "mae_pct_15m": tr.get("mae_pct_15m"),
        },
    }


def quality_bucket(r: dict[str, Any]) -> str:
    econ = r.get("option_economics") or {}
    v = econ.get("net_5m_pct")
    if v is None:
        return "NO_EXACT_OPTION_ECONOMICS"
    v = float(v)
    if v >= 10:
        return "EXCELLENT_5M_GE_10"
    if v >= 3:
        return "GOOD_5M_3_TO_10"
    if v > 0:
        return "SMALL_WIN_5M_0_TO_3"
    if v > -5:
        return "LOSS_5M_0_TO_MINUS5"
    return "LARGE_LOSS_5M_LE_MINUS5"


def top_rank(rows: list[dict[str, Any]], direction: str, n: int = 10) -> list[dict[str, Any]]:
    use = [
        r for r in rows
        if r["direction"] == direction
        and (r.get("option_economics") or {}).get("net_5m_pct") is not None
    ]
    use.sort(key=lambda r: float(r["option_economics"]["net_5m_pct"]), reverse=True)
    return use[:n]


def bottom_rank(rows: list[dict[str, Any]], direction: str, n: int = 10) -> list[dict[str, Any]]:
    use = [
        r for r in rows
        if r["direction"] == direction
        and (r.get("option_economics") or {}).get("net_5m_pct") is not None
    ]
    use.sort(key=lambda r: float(r["option_economics"]["net_5m_pct"]))
    return use[:n]


def compact_rank(r: dict[str, Any]) -> dict[str, Any]:
    econ = r.get("option_economics") or {}
    oi = r.get("oi") or {}
    fut = r.get("futures") or {}
    pf = r.get("price_features") or {}
    return {
        "block": r.get("block"),
        "session_date": r.get("session_date"),
        "setup_type": r.get("setup_type"),
        "direction": r.get("direction"),
        "decision_family": r.get("decision_family"),
        "signal_timestamp": r.get("signal_timestamp"),
        "price_features": pf,
        "price_pass_count": r.get("price_pass_count"),
        "oi_quality": r.get("oi_quality"),
        "ce_state": oi.get("ce_state"),
        "pe_state": oi.get("pe_state"),
        "futures_vwap_distance_points": fut.get("distance_points"),
        "futures_vwap_aligned": fut.get("aligned"),
        "option_side": econ.get("option_side"),
        "strike": econ.get("strike"),
        "net_1m_pct": econ.get("net_1m_pct"),
        "net_3m_pct": econ.get("net_3m_pct"),
        "net_5m_pct": econ.get("net_5m_pct"),
        "net_10m_pct": econ.get("net_10m_pct"),
        "net_15m_pct": econ.get("net_15m_pct"),
        "mfe_pct_15m": econ.get("mfe_pct_15m"),
        "mae_pct_15m": econ.get("mae_pct_15m"),
    }



def walk_dicts(x: Any):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk_dicts(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_dicts(v)


def diagnostic_feature_index(doc: dict[str, Any]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """
    Extract actual checkpoint feature VALUES from MIDPOINT_FAILURE_DIAGNOSTICS_V2_2.

    The diagnostics artifact has evolved across research versions, so this uses
    field discovery rather than relying on a single container path. Only rows
    with an actual `price_features` dict are indexed.
    """
    out: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for r in walk_dicts(doc):
        pf = r.get("price_features")
        if not isinstance(pf, dict) or not pf:
            continue
        block = str(r.get("block") or "")
        session = str(r.get("session_date") or "")
        setup = str(r.get("setup_type") or "")
        ts_raw = pick(
            r,
            "timestamp",
            "checkpoint_timestamp",
            "provider_timestamp",
            "t3_timestamp",
            "datetime",
            "time",
        )
        ts = parse_ts(ts_raw)
        if block in ALLOWED_BLOCKS and session and setup and ts:
            out[(block, session, setup, ts.isoformat())] = r
    return out


def actual_t3_features(
    block: str,
    session: str,
    setup: str,
    t3_timestamp: str | None,
    diag_idx: dict[tuple[str, str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    if not t3_timestamp:
        return {}
    ts = parse_ts(t3_timestamp)
    if not ts:
        return {}
    row = diag_idx.get((block, session, setup, ts.isoformat()))
    if not row:
        return {}
    pf = dict(row.get("price_features") or {})
    # Normalize historical naming to the frozen V3.2 feature names.
    if "momentum_5m_directional" not in pf and "momentum_5m" in pf:
        pf["momentum_5m_directional"] = pf.get("momentum_5m")
    return {
        k: pf.get(k)
        for k in (
            "acceptance_pct",
            "momentum_5m_directional",
            "progress_points",
            "giveback_from_best_checkpoint_points",
            "consecutive_closes",
            "velocity",
        )
        if pf.get(k) is not None
    }


def load_underlying(items: list[tuple[str, Path]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for block, path in items:
        if block not in ALLOWED_BLOCKS:
            raise ValueError(block)
        for r in load_csv(path):
            ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
            if not ts:
                continue
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            out[(block, session, ts.isoformat())] = {
                "open": num(pick(r, "open")),
                "high": num(pick(r, "high")),
                "low": num(pick(r, "low")),
                "close": num(pick(r, "close")),
            }
    return out


def round_atm_50(spot: float) -> float:
    return float(int((spot + 25.0) // 50.0) * 50)


def load_option_ohlc(items: list[tuple[str, Path]]) -> dict[str, Any]:
    by_contract: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    contract_meta: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen_meta = set()

    for block, path in items:
        if block not in ALLOWED_BLOCKS:
            raise ValueError(block)
        for r in load_csv(path):
            ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
            inst = str(pick(r, "instrument_key", "option_instrument_key") or "")
            if not ts or not inst:
                continue
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            strike = num(pick(r, "strike", "strike_price"))
            side = str(pick(r, "side", "option_side", "instrument_type") or "").upper()
            if side in {"CALL", "CE"}:
                side = "CE"
            elif side in {"PUT", "PE"}:
                side = "PE"

            by_contract[(block, session, inst)][ts.isoformat()] = {
                "open": num(pick(r, "open")),
                "high": num(pick(r, "high")),
                "low": num(pick(r, "low")),
                "close": num(pick(r, "close")),
            }
            mk = (block, session, inst)
            if mk not in seen_meta and strike is not None and side in {"CE", "PE"}:
                contract_meta[(block, session)].append({
                    "instrument_key": inst,
                    "strike": float(strike),
                    "side": side,
                })
                seen_meta.add(mk)
    return {"series": by_contract, "meta": contract_meta}


def counterfactual_exact_atm_economics(
    row: dict[str, Any],
    underlying: dict[tuple[str, str, str], dict[str, Any]],
    option_data: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Attach a common, comparable retrospective economic path for every structural
    event at its T3 timestamp in the ORIGINAL structural direction.

    This is NOT a strategy trade for rejected events; it is a counterfactual
    measurement used only to compare opportunity quality across all 184 events.
    """
    block = row["block"]
    session = row["session_date"]
    direction = row["direction"]
    ts = parse_ts(row.get("t3_timestamp") or row.get("signal_timestamp"))
    if not ts:
        return None, "MISSING_T3_TIMESTAMP"

    under = underlying.get((block, session, ts.isoformat()))
    if not under or under.get("close") is None:
        return None, "MISSING_UNDERLYING_T3_CLOSE"

    atm = round_atm_50(float(under["close"]))
    side = "CE" if direction == "BULLISH" else "PE"
    candidates = [
        m for m in option_data["meta"].get((block, session), [])
        if m["side"] == side and abs(float(m["strike"]) - atm) < 1e-9
    ]
    if len(candidates) != 1:
        return None, (
            "MISSING_EXACT_ATM_CONTRACT" if not candidates
            else "AMBIGUOUS_EXACT_ATM_CONTRACT"
        )

    meta = candidates[0]
    series = option_data["series"].get((block, session, meta["instrument_key"]), {})
    entry_ts = ts + timedelta(minutes=1)
    entry_row = series.get(entry_ts.isoformat())
    if not entry_row or entry_row.get("open") is None:
        return None, "MISSING_NEXT_MINUTE_OPTION_OPEN"

    entry = float(entry_row["open"])
    econ = {
        "basis": "COUNTERFACTUAL_T3_ORIGINAL_DIRECTION_EXACT_ATM",
        "is_actual_strategy_trade": False,
        "option_side": side,
        "strike": atm,
        "instrument_key": meta["instrument_key"],
        "entry_timestamp": entry_ts.isoformat(),
        "entry_price": entry,
    }
    for h in HORIZONS:
        exit_row = series.get((entry_ts + timedelta(minutes=h)).isoformat())
        econ[f"net_{h}m_pct"] = (
            None if not exit_row or exit_row.get("close") is None
            else ((float(exit_row["close"]) / entry) - 1.0) * 100.0 - 0.5
        )

    path = [
        series.get((entry_ts + timedelta(minutes=i)).isoformat())
        for i in range(15)
    ]
    highs = [float(x["high"]) for x in path if x and x.get("high") is not None]
    lows = [float(x["low"]) for x in path if x and x.get("low") is not None]
    econ["mfe_pct_15m"] = (
        ((max(highs) / entry) - 1.0) * 100.0 if highs else None
    )
    econ["mae_pct_15m"] = (
        ((min(lows) / entry) - 1.0) * 100.0 if lows else None
    )
    econ["complete_15m_path"] = all(x is not None for x in path)
    return econ, None


def read_session_dates(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

def parse_named(v: str) -> tuple[str, Path]:
    b, p = v.split("|", 1)
    if b not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(f"invalid block {b}")
    return b, Path(p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structural", required=True)
    ap.add_argument("--stable-state", required=True)
    ap.add_argument("--controlled-comparison", required=True)
    ap.add_argument("--canonical-option-economics", required=True)
    ap.add_argument("--positioning", action="append", required=True, type=parse_named)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--checkpoint-diagnostics", required=True)
    ap.add_argument("--underlying", action="append", required=True, type=parse_named)
    ap.add_argument("--option-ohlc", action="append", required=True, type=parse_named)
    ap.add_argument("--expected-session-dates-file", required=False)
    ap.add_argument("--sep15-intraday", required=False)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    structural = load_json(Path(args.structural))
    stable_doc = load_json(Path(args.stable_state))
    comparison = load_json(Path(args.controlled_comparison))
    economics = load_json(Path(args.canonical_option_economics))
    checkpoint_diag = load_json(Path(args.checkpoint_diagnostics))

    events = load_structural_events(structural)
    stable_idx = stable_feature_index(stable_doc)
    armc_idx = arm_c_trade_index(comparison)
    all_option_rows = all_option_trade_index(economics)
    positioning = load_positioning(args.positioning)
    futures = load_futures(Path(args.futures_vwap))
    diag_idx = diagnostic_feature_index(checkpoint_diag)
    underlying = load_underlying(args.underlying)
    option_data = load_option_ohlc(args.option_ohlc)

    rows = []
    for e in events:
        block = str(e.get("block"))
        session = str(e.get("session_date"))
        setup = str(e.get("setup_type") or "")
        stable = stable_idx.get((block, session, setup))
        base = {
            "block": block,
            "session_date": session,
            "setup_type": setup,
            "direction": str(e.get("direction")),
            "decision_family": decision_family(e),
            "reference_high": num(e.get("reference_high")),
            "reference_low": num(e.get("reference_low")),
            "reference_midpoint": num(e.get("reference_midpoint")),
            "midpoint_break_timestamp": e.get("midpoint_break_timestamp"),
            "boundary_break_timestamp": e.get("boundary_break_timestamp"),
        }
        base.update(extract_features(e, stable, positioning, futures, diag_idx))
        # Preserve actual strategy economics where available, then build a common
        # counterfactual T3 exact-ATM path for every event for apples-to-apples ranking.
        actual = attach_option_economics(base, armc_idx, all_option_rows)
        base["actual_strategy_option_economics"] = actual.get("option_economics")
        cf, cf_issue = counterfactual_exact_atm_economics(base, underlying, option_data)
        base["option_economics"] = cf
        base["counterfactual_economics_issue"] = cf_issue
        base["quality_bucket"] = quality_bucket(base)
        rows.append(base)

    sessions = sorted({r["session_date"] for r in rows})
    expected_sessions = read_session_dates(
        Path(args.expected_session_dates_file) if args.expected_session_dates_file else None
    )
    session_audit = {
        "structural_unique_session_count": len(sessions),
        "expected_session_count": len(expected_sessions) if expected_sessions else None,
        "extra_in_structural_vs_expected": sorted(set(sessions) - expected_sessions) if expected_sessions else [],
        "missing_in_structural_vs_expected": sorted(expected_sessions - set(sessions)) if expected_sessions else [],
    }

    by_direction = {
        d: summarize([r for r in rows if r["direction"] == d])
        for d in ("BULLISH", "BEARISH")
    }
    by_decision = {
        k: summarize([r for r in rows if r["decision_family"] == k])
        for k in sorted({r["decision_family"] for r in rows})
    }
    quality_counts = dict(Counter(r["quality_bucket"] for r in rows))

    sep7 = [compact_rank(r) for r in rows if r["session_date"] == "2026-09-07"]
    sep15 = None
    if args.sep15_intraday:
        p = Path(args.sep15_intraday)
        if p.exists():
            sep15 = load_json(p)

    econ_issue_counts = dict(Counter(r.get("counterfactual_economics_issue") or "AVAILABLE" for r in rows))
    feature_coverage = dict(Counter(str(r.get("price_features_available_count", 0)) for r in rows))
    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DESCRIPTIVE_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_ONLY",
        "scope": {
            "historical_session_count": len(sessions),
            "historical_event_count": len(rows),
            "blocks": sorted(ALLOWED_BLOCKS),
            "forbidden_blocks": sorted(FORBIDDEN_BLOCKS),
            "sep15_current_day_included_as_external_reference": sep15 is not None,
            "session_count_audit": session_audit,
        },
        "coverage": {
            "counterfactual_option_economics": econ_issue_counts,
            "t3_price_feature_value_count_distribution": feature_coverage,
            "events_with_all_6_t3_feature_values": sum(1 for r in rows if r.get("price_features_available_count") == 6),
        },
        "overall": summarize(rows),
        "by_direction": by_direction,
        "by_decision_family": by_decision,
        "quality_bucket_counts": quality_counts,
        "coverage": result["coverage"],
        "session_count_audit": session_audit,
        "top_bullish_by_5m": [compact_rank(r) for r in top_rank(rows, "BULLISH")],
        "top_bearish_by_5m": [compact_rank(r) for r in top_rank(rows, "BEARISH")],
        "bottom_bullish_by_5m": [compact_rank(r) for r in bottom_rank(rows, "BULLISH")],
        "bottom_bearish_by_5m": [compact_rank(r) for r in bottom_rank(rows, "BEARISH")],
        "sep7_historical_reference": sep7,
        "sep15_external_reference": sep15,
        "events": rows,
        "integrity": {
            "strategy_rules_modified": False,
            "threshold_tuning_performed": False,
            "outcome_used_for_live_selection": False,
            "oos_e_f_g_h_used": False,
            "paper_or_live_order_emission_allowed": False,
            "outcomes_used_only_for_retrospective_grouping_and_ranking": True,
            "global_ranking_uses_common_t3_counterfactual_exact_atm": True,
            "rejected_events_are_not_mislabeled_as_actual_strategy_trades": True,
        },
        "interpretation_guard": (
            "Ranking and quality buckets use realized outcomes only for retrospective research. "
            "They must not be converted directly into live filters without freezing a candidate "
            "rule and validating on fresh precommitted OOS data."
        ),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")

    print(json.dumps({
        "research_version": RESEARCH_VERSION,
        "scope": result["scope"],
        "quality_bucket_counts": quality_counts,
        "top_bullish_by_5m": result["top_bullish_by_5m"][:5],
        "top_bearish_by_5m": result["top_bearish_by_5m"][:5],
        "bottom_bullish_by_5m": result["bottom_bullish_by_5m"][:5],
        "bottom_bearish_by_5m": result["bottom_bearish_by_5m"][:5],
        "sep7_historical_reference": sep7,
        "output": str(out),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
