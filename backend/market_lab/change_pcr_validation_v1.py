from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

MODEL = "CHANGE_PCR_VALIDATION_V1"
HORIZONS = ("5m", "10m", "15m")


def _sign(value: float | None) -> str:
    if value is None:
        return "NA"
    if value > 0:
        return "+"
    if value < 0:
        return "-"
    return "0"


def delta_pattern(ce_delta: float | None, pe_delta: float | None) -> str:
    if ce_delta is None or pe_delta is None:
        return "NA"
    return f"CE{_sign(ce_delta)}/PE{_sign(pe_delta)}"


def change_pcr(ce_delta: float | None, pe_delta: float | None) -> float | None:
    """PE OI change / CE OI change.

    Intentionally returns None when CE delta is zero or either delta is unavailable.
    No infinity, epsilon substitution, nearest value, or interpolation is used.
    """
    if ce_delta is None or pe_delta is None or ce_delta == 0:
        return None
    return pe_delta / ce_delta


def existing_horizon_state(
    imbalance: float | None,
    pcr_change: float | None,
) -> str:
    """Mirror the frozen cross-date research definition; do not use Change-PCR."""
    if imbalance is None or pcr_change is None:
        return "NA"
    if imbalance > 0 and pcr_change > 0:
        return "BULLISH"
    if imbalance < 0 and pcr_change < 0:
        return "BEARISH"
    return "MIXED"


def change_pcr_mechanics(
    ce_delta: float | None,
    pe_delta: float | None,
    ratio: float | None,
) -> str:
    """Descriptive mechanics only; NOT a trading classification."""
    if ce_delta is None or pe_delta is None:
        return "NA"
    if ce_delta == 0:
        if pe_delta > 0:
            return "CE_FLAT_PE_BUILD"
        if pe_delta < 0:
            return "CE_FLAT_PE_UNWIND"
        return "BOTH_FLAT"

    if ce_delta > 0 and pe_delta < 0:
        return "CE_BUILD_PE_UNWIND"
    if ce_delta < 0 and pe_delta > 0:
        return "CE_UNWIND_PE_BUILD"

    if ce_delta > 0 and pe_delta > 0:
        if ratio is None:
            return "BOTH_BUILD_UNDEFINED_RATIO"
        if ratio > 1:
            return "BOTH_BUILD_PE_DOMINANT"
        if ratio < 1:
            return "BOTH_BUILD_CE_DOMINANT"
        return "BOTH_BUILD_BALANCED"

    if ce_delta < 0 and pe_delta < 0:
        # ratio is positive here because both numerator and denominator are negative.
        # ratio > 1 means |PE unwind| > |CE unwind|.
        if ratio is None:
            return "BOTH_UNWIND_UNDEFINED_RATIO"
        if ratio > 1:
            return "BOTH_UNWIND_PE_DOMINANT"
        if ratio < 1:
            return "BOTH_UNWIND_CE_DOMINANT"
        return "BOTH_UNWIND_BALANCED"

    if ce_delta == 0:
        return "CE_FLAT"
    if pe_delta == 0:
        return "PE_FLAT"
    return "OTHER"


def _load_audit(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("status") != "PASS":
        raise ValueError(f"{path}: audit status is not PASS")
    if not isinstance(payload.get("rows"), list):
        raise ValueError(f"{path}: missing rows list")
    return payload


def _row_for_horizon(
    session_date: str,
    row: dict[str, Any],
    horizon: str,
) -> dict[str, Any]:
    ce_delta = row.get(f"ce_delta_{horizon}")
    pe_delta = row.get(f"pe_delta_{horizon}")
    imbalance = row.get(f"imbalance_{horizon}")
    pcr_change = row.get(f"pcr_change_{horizon}")
    ratio = change_pcr(ce_delta, pe_delta)

    return {
        "session_date": session_date,
        "timestamp": row.get("timestamp"),
        "spot": row.get("spot"),
        "moving_atm": row.get("moving_atm"),
        "horizon": horizon,
        "ce_delta": ce_delta,
        "pe_delta": pe_delta,
        "delta_pattern": delta_pattern(ce_delta, pe_delta),
        "change_pcr": ratio,
        "change_pcr_mechanics": change_pcr_mechanics(ce_delta, pe_delta, ratio),
        "oi_imbalance": imbalance,
        "regular_pcr_change": pcr_change,
        "existing_horizon_state": existing_horizon_state(imbalance, pcr_change),
        "futures_oi_direction": row.get("futures_oi_direction"),
        "futures_oi_status": row.get("futures_oi_status"),
        "vwap_side": row.get("vwap_side"),
        "session_pcr_change": row.get("session_pcr_change_0920_to_now"),
        "evaluation_label": row.get("evaluation_label"),
        "fallback_used": row.get("fallback_used"),
    }


def build_rows(audit_paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    sessions: list[str] = []

    for path in audit_paths:
        payload = _load_audit(path)
        session_date = str(payload.get("session_date") or "")
        if not session_date:
            raise ValueError(f"{path}: missing session_date")
        sessions.append(session_date)

        for row in payload["rows"]:
            for horizon in HORIZONS:
                out.append(_row_for_horizon(session_date, row, horizon))

    return out, sessions


def _summary(rows: list[dict[str, Any]], sessions: list[str]) -> dict[str, Any]:
    by_session: dict[str, Any] = {}

    for session in sessions:
        sr = [r for r in rows if r["session_date"] == session]
        mechanics: dict[str, int] = {}
        state_mechanics: dict[str, dict[str, int]] = {
            "BULLISH": {},
            "BEARISH": {},
            "MIXED": {},
            "NA": {},
        }
        horizon_stats: dict[str, Any] = {}

        for r in sr:
            m = r["change_pcr_mechanics"]
            mechanics[m] = mechanics.get(m, 0) + 1
            state = r["existing_horizon_state"]
            bucket = state_mechanics.setdefault(state, {})
            bucket[m] = bucket.get(m, 0) + 1

        for horizon in HORIZONS:
            hr = [r for r in sr if r["horizon"] == horizon]
            valid_ratios = [r["change_pcr"] for r in hr if r["change_pcr"] is not None]
            horizon_stats[horizon] = {
                "rows": len(hr),
                "valid_change_pcr": len(valid_ratios),
                "undefined_change_pcr": len(hr) - len(valid_ratios),
                "mean_change_pcr": (
                    sum(valid_ratios) / len(valid_ratios) if valid_ratios else None
                ),
                "existing_bullish": sum(
                    1 for r in hr if r["existing_horizon_state"] == "BULLISH"
                ),
                "existing_bearish": sum(
                    1 for r in hr if r["existing_horizon_state"] == "BEARISH"
                ),
                "existing_mixed": sum(
                    1 for r in hr if r["existing_horizon_state"] == "MIXED"
                ),
                "existing_na": sum(
                    1 for r in hr if r["existing_horizon_state"] == "NA"
                ),
            }

        by_session[session] = {
            "row_count": len(sr),
            "mechanics_counts": mechanics,
            "mechanics_by_existing_state": state_mechanics,
            "by_horizon": horizon_stats,
        }

    return {
        "status": "PASS",
        "model": MODEL,
        "sessions": sessions,
        "session_count": len(sessions),
        "row_count": len(rows),
        "definition": {
            "change_pcr": "PE_OI_CHANGE / CE_OI_CHANGE",
            "undefined_when": "CE delta is zero or either delta is unavailable",
            "role": "DESCRIPTIVE_RESEARCH_ONLY",
            "existing_state_unchanged": True,
        },
        "by_session": by_session,
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Research-only Change-PCR validation over frozen V1.1 audit JSONs."
    )
    p.add_argument(
        "--audit-json",
        action="append",
        required=True,
        help="Path to an OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1 JSON. Repeat per session.",
    )
    p.add_argument("--rows-csv", required=True)
    p.add_argument("--summary-json", required=True)
    args = p.parse_args(argv)

    audit_paths = [Path(x) for x in args.audit_json]
    rows, sessions = build_rows(audit_paths)
    summary = _summary(rows, sessions)

    write_csv(rows, Path(args.rows_csv))
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
