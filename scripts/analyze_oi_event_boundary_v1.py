#!/usr/bin/env python3
"""OI event-boundary attribution V1.

Research-only, read-only diagnostic for one known price event.

The analyzer answers a deliberately simple question:
    What was the overall option OI structure before the event, and how did
    that same overall OI structure change at/after the event?

It reads LIVE_SHADOW_STEP_AUDIT_V1 NORMALIZED_FEATURES records only.
Consequently V1 reports the producer's frozen moving ATM +/-5 basket.  It does
not attempt to reconstruct per-strike or +/-2 OI from data that is not present
in the audit.

For every checkpoint it preserves:
- current CE OI / PE OI / total OI
- rolling exact 5m CE/PE delta, delta %, imbalance, PCR and PCR change
- cumulative CE/PE OI change from the exact pre-event baseline checkpoint
- cumulative CE/PE OI change % from that baseline
- cumulative imbalance and cumulative PCR change from that baseline

No nearest-time fallback is permitted.  Missing baseline/event checkpoints
fail clearly.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _pct(delta: float | None, base: float | None) -> float | None:
    if delta is None or base in (None, 0):
        return None
    return delta / base * 100.0


def _pcr(pe: float | None, ce: float | None) -> float | None:
    if pe is None or ce in (None, 0):
        return None
    return pe / ce


def _fmt_m(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1_000_000.0:+.3f}M"


def _fmt_oi(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1_000_000.0:.3f}M"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.3f}%"


def _fmt_dec(value: float | None, places: int = 6) -> str:
    if value is None:
        return "—"
    return f"{value:+.{places}f}"


def _latest_normalized_rows(path: Path, session_date: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            checkpoint = str(record.get("checkpoint") or "")
            if not checkpoint.startswith(session_date):
                continue
            if record.get("stage") != "NORMALIZED_FEATURES":
                continue
            sequence = int(record.get("sequence") or 0)
            previous = latest.get(checkpoint)
            if previous is None or sequence >= int(previous.get("sequence") or 0):
                latest[checkpoint] = record
    return [latest[key] for key in sorted(latest)]


def _time_of(checkpoint: str) -> str:
    return datetime.fromisoformat(checkpoint).strftime("%H:%M")


def _extract_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        checkpoint = str(record["checkpoint"])
        payload = record.get("payload") or {}
        h5 = (payload.get("horizons") or {}).get("5m") or {}
        current_ce = _as_float(h5.get("current_ce_oi"))
        current_pe = _as_float(h5.get("current_pe_oi"))
        prior_ce = _as_float(h5.get("prior_ce_oi"))
        prior_pe = _as_float(h5.get("prior_pe_oi"))
        ce_delta = _as_float(h5.get("ce_delta"))
        pe_delta = _as_float(h5.get("pe_delta"))
        current_pcr = _as_float(h5.get("current_pcr"))
        prior_pcr = _as_float(h5.get("prior_pcr"))
        row = {
            "checkpoint": checkpoint,
            "time": _time_of(checkpoint),
            "spot": _as_float(payload.get("spot")),
            "moving_atm": _as_float(payload.get("moving_atm")),
            "moving_strikes": payload.get("moving_strikes") or [],
            "all3_state": payload.get("all3_state"),
            "state_5m": h5.get("state", "NA"),
            "current_ce_oi": current_ce,
            "current_pe_oi": current_pe,
            "current_total_oi": (current_ce + current_pe) if current_ce is not None and current_pe is not None else None,
            "prior_ce_oi_5m": prior_ce,
            "prior_pe_oi_5m": prior_pe,
            "ce_delta_5m": ce_delta,
            "pe_delta_5m": pe_delta,
            "ce_delta_5m_pct": _pct(ce_delta, prior_ce),
            "pe_delta_5m_pct": _pct(pe_delta, prior_pe),
            "net_total_oi_delta_5m": (ce_delta + pe_delta) if ce_delta is not None and pe_delta is not None else None,
            "imbalance_5m": _as_float(h5.get("imbalance")),
            "prior_pcr_5m": prior_pcr,
            "current_pcr_5m": current_pcr,
            "pcr_change_5m": _as_float(h5.get("pcr_change")),
        }
        rows.append(row)
    return rows


def _exact_row(rows: list[dict[str, Any]], time_text: str, label: str) -> dict[str, Any]:
    matches = [row for row in rows if row["time"] == time_text]
    if len(matches) != 1:
        raise SystemExit(
            f"Required exact {label} checkpoint {time_text} not found exactly once; found {len(matches)}. "
            "No nearest-time fallback is allowed."
        )
    return matches[0]


def _phase(time_text: str, baseline_time: str, event_time: str) -> str:
    if time_text < baseline_time:
        return "PRE_HISTORY"
    if time_text == baseline_time:
        return "PRE_EVENT_BASELINE"
    if time_text < event_time:
        return "PRE_EVENT"
    if time_text == event_time:
        return "EVENT"
    return "POST_EVENT"


def _add_baseline_changes(
    rows: list[dict[str, Any]], baseline: dict[str, Any], baseline_time: str, event_time: str
) -> None:
    bce = baseline["current_ce_oi"]
    bpe = baseline["current_pe_oi"]
    bpcr = baseline["current_pcr_5m"] or _pcr(bpe, bce)
    if bce is None or bpe is None:
        raise SystemExit("Baseline checkpoint is missing current CE/PE OI totals; cannot compute event attribution.")
    for row in rows:
        ce = row["current_ce_oi"]
        pe = row["current_pe_oi"]
        ce_change = ce - bce if ce is not None else None
        pe_change = pe - bpe if pe is not None else None
        pcr = row["current_pcr_5m"] or _pcr(pe, ce)
        row.update(
            {
                "phase": _phase(row["time"], baseline_time, event_time),
                "baseline_time": baseline_time,
                "baseline_ce_oi": bce,
                "baseline_pe_oi": bpe,
                "ce_change_from_baseline": ce_change,
                "pe_change_from_baseline": pe_change,
                "ce_change_from_baseline_pct": _pct(ce_change, bce),
                "pe_change_from_baseline_pct": _pct(pe_change, bpe),
                "net_total_oi_change_from_baseline": (
                    ce_change + pe_change if ce_change is not None and pe_change is not None else None
                ),
                "cumulative_imbalance_from_baseline": (
                    pe_change - ce_change if ce_change is not None and pe_change is not None else None
                ),
                "pcr_change_from_baseline": (pcr - bpcr) if pcr is not None and bpcr is not None else None,
            }
        )


def _print_snapshot(title: str, row: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(f"checkpoint       : {row['time']} ({row['checkpoint']})")
    print(f"spot             : {row['spot']}")
    print(f"moving ATM       : {row['moving_atm']}")
    print(f"CE total OI      : {_fmt_oi(row['current_ce_oi'])}")
    print(f"PE total OI      : {_fmt_oi(row['current_pe_oi'])}")
    print(f"CE+PE total OI   : {_fmt_oi(row['current_total_oi'])}")
    print(f"5m CE delta      : {_fmt_m(row['ce_delta_5m'])} ({_fmt_pct(row['ce_delta_5m_pct'])})")
    print(f"5m PE delta      : {_fmt_m(row['pe_delta_5m'])} ({_fmt_pct(row['pe_delta_5m_pct'])})")
    print(f"5m net OI delta  : {_fmt_m(row['net_total_oi_delta_5m'])}")
    print(f"5m imbalance     : {_fmt_m(row['imbalance_5m'])}")
    print(f"PCR              : {_fmt_dec(row['current_pcr_5m'])}")
    print(f"5m PCR change    : {_fmt_dec(row['pcr_change_5m'])}")
    print(f"5m state         : {row['state_5m']}")
    print(f"ALL3             : {row['all3_state']}")


def _print_transition(rows: list[dict[str, Any]]) -> None:
    print("\n=== OI TRANSITION AROUND EVENT ===")
    print(
        "TIME   PHASE               SPOT      CE_OI      PE_OI      5m_CEΔ    5m_PEΔ    5m_IMB     "
        "CEΔ_BASE   PEΔ_BASE   CUM_IMB    PCR       PCRΔ5     PCRΔ_BASE"
    )
    print("-" * 176)
    for row in rows:
        spot = "—" if row["spot"] is None else f"{row['spot']:.2f}"
        pcr = "—" if row["current_pcr_5m"] is None else f"{row['current_pcr_5m']:.4f}"
        print(
            f"{row['time']:5} "
            f"{row['phase']:19} "
            f"{spot:>8} "
            f"{_fmt_oi(row['current_ce_oi']):>10} "
            f"{_fmt_oi(row['current_pe_oi']):>10} "
            f"{_fmt_m(row['ce_delta_5m']):>9} "
            f"{_fmt_m(row['pe_delta_5m']):>9} "
            f"{_fmt_m(row['imbalance_5m']):>10} "
            f"{_fmt_m(row['ce_change_from_baseline']):>10} "
            f"{_fmt_m(row['pe_change_from_baseline']):>10} "
            f"{_fmt_m(row['cumulative_imbalance_from_baseline']):>10} "
            f"{pcr:>8} "
            f"{_fmt_dec(row['pcr_change_5m'], 4):>9} "
            f"{_fmt_dec(row['pcr_change_from_baseline'], 4):>10}"
        )


def _print_event_changes(event: dict[str, Any], post_rows: list[dict[str, Any]]) -> None:
    print("\n=== CHANGE FROM PRE-EVENT BASELINE ===")
    print("TIME   PHASE          CE CHANGE         PE CHANGE         NET OI CHANGE     CUM IMBALANCE      PCR CHANGE")
    print("-" * 116)
    for row in [event, *post_rows]:
        print(
            f"{row['time']:5} {row['phase']:14} "
            f"{_fmt_m(row['ce_change_from_baseline']):>16} "
            f"{_fmt_m(row['pe_change_from_baseline']):>17} "
            f"{_fmt_m(row['net_total_oi_change_from_baseline']):>17} "
            f"{_fmt_m(row['cumulative_imbalance_from_baseline']):>18} "
            f"{_fmt_dec(row['pcr_change_from_baseline'], 6):>15}"
        )


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "checkpoint", "time", "phase", "spot", "moving_atm", "all3_state", "state_5m",
        "current_ce_oi", "current_pe_oi", "current_total_oi",
        "prior_ce_oi_5m", "prior_pe_oi_5m",
        "ce_delta_5m", "pe_delta_5m", "ce_delta_5m_pct", "pe_delta_5m_pct",
        "net_total_oi_delta_5m", "imbalance_5m",
        "prior_pcr_5m", "current_pcr_5m", "pcr_change_5m",
        "baseline_time", "baseline_ce_oi", "baseline_pe_oi",
        "ce_change_from_baseline", "pe_change_from_baseline",
        "ce_change_from_baseline_pct", "pe_change_from_baseline_pct",
        "net_total_oi_change_from_baseline", "cumulative_imbalance_from_baseline",
        "pcr_change_from_baseline",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--step-audit", default="data/live-observation/shadow-v1/step-audit.jsonl")
    parser.add_argument("--from-time", default="10:10")
    parser.add_argument("--to-time", default="11:05")
    parser.add_argument("--baseline-time", default="10:35")
    parser.add_argument("--event-time", default="10:40")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    if not (args.from_time <= args.baseline_time < args.event_time <= args.to_time):
        raise SystemExit("Require from-time <= baseline-time < event-time <= to-time.")

    audit_path = Path(args.step_audit)
    if not audit_path.exists():
        raise SystemExit(f"Step audit not found: {audit_path}")

    records = _latest_normalized_rows(audit_path, args.date)
    rows = _extract_rows(records)
    rows = [row for row in rows if args.from_time <= row["time"] <= args.to_time]
    if not rows:
        raise SystemExit("No NORMALIZED_FEATURES records found for requested date/window.")

    baseline = _exact_row(rows, args.baseline_time, "baseline")
    event = _exact_row(rows, args.event_time, "event")
    _add_baseline_changes(rows, baseline, args.baseline_time, args.event_time)

    print(
        f"session={args.date} window={args.from_time}-{args.to_time} "
        f"baseline={args.baseline_time} event={args.event_time} checkpoints={len(rows)}"
    )
    print("basket=existing LIVE_NORMALIZED_FEATURE_PRODUCER moving ATM +/-5")
    _print_snapshot("PRE-EVENT BASELINE", baseline)
    _print_snapshot("EVENT CHECKPOINT", event)
    _print_transition(rows)
    post_rows = [row for row in rows if row["time"] > args.event_time]
    _print_event_changes(event, post_rows)

    out = Path(args.csv) if args.csv else Path(
        f"data/live-observation/analysis/{args.date}-oi-event-boundary-{args.event_time.replace(':','')}-v1.csv"
    )
    _write_csv(rows, out)
    print(f"\nCSV: {out}")
    print("NOTE: V1 is overall moving ATM +/-5 only; step-audit does not contain per-strike OI or an ATM +/-2 reconstruction.")


if __name__ == "__main__":
    main()
