
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

MODEL = "CANDLE_BY_CANDLE_VALIDATION_V1"


def _fmt_m(v: Any) -> str:
    if v is None:
        return "NA"
    try:
        return f"{float(v)/1_000_000:.3f}M"
    except Exception:
        return str(v)


def _fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "NA"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return str(v)


def _dir_from(v: Any) -> str:
    if v is None:
        return "NA"
    v = float(v)
    return "BULLISH" if v > 0 else "BEARISH" if v < 0 else "FLAT"


def _session_context(row: dict[str, Any]) -> str:
    ce = row.get("ce_session_delta")
    pe = row.get("pe_session_delta")
    imb = row.get("session_imbalance")
    if ce is None or pe is None or imb is None:
        return "NA"
    d = _dir_from(imb)
    return f"{d} | CE={_fmt_m(ce)} PE={_fmt_m(pe)} IMB={_fmt_m(imb)}"


def _recent_context(row: dict[str, Any]) -> str:
    return (
        f"5m={_fmt_m(row.get('imbalance_5m'))} "
        f"10m={_fmt_m(row.get('imbalance_10m'))} "
        f"15m={_fmt_m(row.get('imbalance_15m'))}"
    )


def _pcr_context(row: dict[str, Any]) -> str:
    return (
        f"PCR={_fmt(row.get('pcr_current'),4)} "
        f"5mAgo={_fmt(row.get('pcr_previous_same_strikes_5m'),4)} "
        f"Δ5={_fmt(row.get('pcr_change_5m'),4)} "
        f"10mAgo={_fmt(row.get('pcr_previous_same_strikes_10m'),4)} "
        f"Δ10={_fmt(row.get('pcr_change_10m'),4)} "
        f"15mAgo={_fmt(row.get('pcr_previous_same_strikes_15m'),4)} "
        f"Δ15={_fmt(row.get('pcr_change_15m'),4)}"
    )


def _session_pcr_context(row: dict[str, Any]) -> str:
    return (
        f"09:20={_fmt(row.get('session_pcr_baseline_0920'),4)} "
        f"NOW={_fmt(row.get('session_pcr_current'),4)} "
        f"Δ={_fmt(row.get('session_pcr_change_0920_to_now'),4)}"
    )


def _price_context(row: dict[str, Any]) -> str:
    return (
        f"FUT={_fmt(row.get('futures_close'),2)} "
        f"Δ5={_fmt(row.get('futures_price_change_5m'),2)} "
        f"Δ10={_fmt(row.get('futures_price_change_10m'),2)} "
        f"Δ15={_fmt(row.get('futures_price_change_15m'),2)}"
    )


def _strategy_context(row: dict[str, Any]) -> str:
    bits = []
    if row.get("strategy_p1"):
        bits.append(f"P1={row['strategy_p1']}")
    if row.get("strategy_wait_p2"):
        bits.append(f"WAIT_P2={row['strategy_wait_p2']}")
    if row.get("strategy_p2_confirmed"):
        bits.append(f"P2_OK={row['strategy_p2_confirmed']}")
    if row.get("strategy_p2_failed"):
        bits.append(f"P2_FAIL={row['strategy_p2_failed']}")
    if row.get("strategy_vwap_rejected"):
        bits.append(f"VWAP_REJECT={row['strategy_vwap_rejected']}")
    return " | ".join(bits) if bits else "NO_ACTION"


def _interpret(row: dict[str, Any]) -> str:
    parts = []

    recent = row.get("imbalance_5m")
    if recent is not None:
        parts.append(f"recent OI {_dir_from(recent).lower()}")

    futdir = row.get("futures_oi_direction")
    status = row.get("futures_oi_status")
    if futdir and status:
        parts.append(f"futures OI {futdir.lower()} ({status})")

    pcr = row.get("pcr_change_5m")
    if pcr is not None:
        parts.append("PCR rising" if pcr > 0 else "PCR falling" if pcr < 0 else "PCR flat")

    side = row.get("vwap_side")
    if side:
        parts.append(f"VWAP {side.lower()}")

    sess = row.get("session_imbalance")
    if sess is not None:
        parts.append(f"session {_dir_from(sess).lower()}")

    return "; ".join(parts)


def build_rows(audit: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for row in audit.get("rows", []):
        if row.get("status") != "PASS":
            continue
        out.append({
            "timestamp": row.get("timestamp"),
            "spot": row.get("spot"),
            "moving_atm": row.get("moving_atm"),
            "moving_atm_pm5_strikes": row.get("moving_strikes"),
            "price_context": _price_context(row),

            "recent_ce_delta_5m": row.get("ce_delta_5m"),
            "recent_pe_delta_5m": row.get("pe_delta_5m"),
            "recent_imbalance_5m": row.get("imbalance_5m"),
            "recent_imbalance_10m": row.get("imbalance_10m"),
            "recent_imbalance_15m": row.get("imbalance_15m"),
            "recent_oi_summary": _recent_context(row),

            "pcr_current": row.get("pcr_current"),
            "pcr_5m_ago_same_strikes": row.get("pcr_previous_same_strikes_5m"),
            "pcr_change_5m": row.get("pcr_change_5m"),
            "pcr_10m_ago_same_strikes": row.get("pcr_previous_same_strikes_10m"),
            "pcr_change_10m": row.get("pcr_change_10m"),
            "pcr_15m_ago_same_strikes": row.get("pcr_previous_same_strikes_15m"),
            "pcr_change_15m": row.get("pcr_change_15m"),
            "pcr_summary": _pcr_context(row),

            "fixed_0920_atm": row.get("morning_fixed_atm"),
            "fixed_0920_pm5_strikes": row.get("fixed_strikes"),
            "ce_session_delta_0920_to_now": row.get("ce_session_delta"),
            "pe_session_delta_0920_to_now": row.get("pe_session_delta"),
            "session_imbalance_0920_to_now": row.get("session_imbalance"),
            "session_oi_summary": _session_context(row),
            "session_pcr_0920": row.get("session_pcr_baseline_0920"),
            "session_pcr_now": row.get("session_pcr_current"),
            "session_pcr_change_0920_to_now": row.get("session_pcr_change_0920_to_now"),
            "session_pcr_summary": _session_pcr_context(row),

            "futures_oi": row.get("futures_oi"),
            "futures_oi_change_5m": row.get("futures_oi_change_5m"),
            "futures_oi_status": row.get("futures_oi_status"),
            "futures_oi_direction": row.get("futures_oi_direction"),
            "bullish_oi_status_streak": row.get("bullish_oi_status_streak"),
            "bearish_oi_status_streak": row.get("bearish_oi_status_streak"),

            "vwap": row.get("vwap"),
            "vwap_distance": row.get("vwap_distance"),
            "vwap_side": row.get("vwap_side"),

            "strategy_events": row.get("strategy_events"),
            "strategy_summary": _strategy_context(row),
            "evaluation_label": row.get("evaluation_label"),

            "candle_interpretation": _interpret(row),
        })
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_text(path: Path, audit: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{MODEL}",
        f"session_date={audit.get('session_date')}",
        f"research_basket=moving ATM±5 ({audit.get('research_strike_count', 'NA')} strikes)",
        f"session_basket=fixed 09:20 ATM±5",
        "",
    ]
    for r in rows:
        lines += [
            f"=== {r['timestamp']} ===",
            f"Spot/ATM: spot={r['spot']} moving_atm={r['moving_atm']}",
            f"PRICE: {r['price_context']}",
            f"RECENT OI (moving ATM±5, same physical strikes): {r['recent_oi_summary']}",
            f"PCR (same-strike): {r['pcr_summary']}",
            f"SESSION OI (fixed 09:20 ATM±5 → now): {r['session_oi_summary']}",
            f"SESSION PCR (fixed 09:20 ATM±5 → now): {r['session_pcr_summary']}",
            f"FUTURES OI: {r['futures_oi_status']} / {r['futures_oi_direction']} ΔOI5={_fmt_m(r['futures_oi_change_5m'])}",
            f"VWAP: {r['vwap_side']} dist={_fmt(r['vwap_distance'],2)}",
            f"STRATEGY: {r['strategy_summary']}",
            f"EVALUATION LABEL: {r['evaluation_label'] or 'NA'}",
            f"INTERPRETATION: {r['candle_interpretation']}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--audit-json", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--text-output", type=Path, required=True)
    args = ap.parse_args()

    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    if audit.get("model") != "OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1":
        raise SystemExit(
            f"Expected OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1, got {audit.get('model')}"
        )

    rows = build_rows(audit)
    write_csv(args.csv, rows)
    write_text(args.text_output, audit, rows)

    print(json.dumps({
        "status": "PASS",
        "model": MODEL,
        "session_date": audit.get("session_date"),
        "candles": len(rows),
        "csv": str(args.csv),
        "text_output": str(args.text_output),
    }, indent=2))


if __name__ == "__main__":
    main()
