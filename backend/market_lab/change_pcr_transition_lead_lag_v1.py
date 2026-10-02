from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable

MODEL = "CHANGE_PCR_TRANSITION_LEAD_LAG_V1"
HORIZONS = ("5m", "10m", "15m")
WINDOW_OFFSETS = (-15, -10, -5, 0, 5, 10, 15)


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            parsed = dict(row)
            for key in ("spot", "moving_atm", "ce_delta", "pe_delta", "change_pcr",
                        "oi_imbalance", "regular_pcr_change", "session_pcr_change"):
                value = parsed.get(key)
                if value in ("", None):
                    parsed[key] = None
                else:
                    try:
                        parsed[key] = float(value)
                    except (TypeError, ValueError):
                        pass
            rows.append(parsed)
    return rows


def _group_candles(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = (row["session_date"], row["timestamp"])
        grouped.setdefault(key, {})[row["horizon"]] = row
    return grouped


def _all3_state(hrows: dict[str, dict[str, Any]]) -> str:
    states = [hrows.get(h, {}).get("existing_horizon_state") for h in HORIZONS]
    if any(s in (None, "", "NA") for s in states):
        return "INCOMPLETE"
    if all(s == "BULLISH" for s in states):
        return "BULLISH_ALL_3"
    if all(s == "BEARISH" for s in states):
        return "BEARISH_ALL_3"
    return "MIXED"


def _ordered_session_candles(grouped: dict[tuple[str, str], dict[str, dict[str, Any]]]) -> dict[str, list[tuple[str, dict[str, dict[str, Any]]]]]:
    by_session: dict[str, list[tuple[str, dict[str, dict[str, Any]]]]] = {}
    for (session, ts), hrows in grouped.items():
        by_session.setdefault(session, []).append((ts, hrows))
    for session in by_session:
        by_session[session].sort(key=lambda x: x[0])
    return by_session


def detect_transitions(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped = _group_candles(rows)
    by_session = _ordered_session_candles(grouped)
    events: list[dict[str, Any]] = []

    for session, candles in by_session.items():
        prior_directional_idx = None
        prior_directional_state = None

        for idx, (ts, hrows) in enumerate(candles):
            state = _all3_state(hrows)
            if state not in ("BULLISH_ALL_3", "BEARISH_ALL_3"):
                continue

            if prior_directional_state and state != prior_directional_state:
                events.append({
                    "session_date": session,
                    "transition_timestamp": ts,
                    "transition_index": idx,
                    "from_state": prior_directional_state,
                    "to_state": state,
                    "prior_directional_index": prior_directional_idx,
                })

            prior_directional_state = state
            prior_directional_idx = idx

    return events


def _directional_mechanics_score(row: dict[str, Any], target: str) -> int | None:
    """Ordinal descriptive score only; no threshold optimization.

    +2 = mechanically strong support for target direction
    +1 = mechanically mild support
     0 = neutral/undefined/mixed mechanics
    -1/-2 = support for opposite direction

    This is not a trading signal. It lets the study compare mechanics symmetrically.
    """
    mech = row.get("change_pcr_mechanics")
    if not mech or mech == "NA":
        return None

    bullish = {
        "CE_UNWIND_PE_BUILD": 2,
        "BOTH_BUILD_PE_DOMINANT": 1,
        "BOTH_UNWIND_CE_DOMINANT": 1,
    }
    bearish = {
        "CE_BUILD_PE_UNWIND": 2,
        "BOTH_BUILD_CE_DOMINANT": 1,
        "BOTH_UNWIND_PE_DOMINANT": 1,
    }

    if target == "BULLISH_ALL_3":
        if mech in bullish:
            return bullish[mech]
        if mech in bearish:
            return -bearish[mech]
    elif target == "BEARISH_ALL_3":
        if mech in bearish:
            return bearish[mech]
        if mech in bullish:
            return -bullish[mech]

    return 0


def build_event_windows(
    rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped = _group_candles(rows)
    by_session = _ordered_session_candles(grouped)
    out: list[dict[str, Any]] = []

    for event_id, event in enumerate(events, start=1):
        session = event["session_date"]
        candles = by_session[session]
        center = event["transition_index"]
        target = event["to_state"]

        for offset_minutes in WINDOW_OFFSETS:
            step = offset_minutes // 5
            idx = center + step
            if idx < 0 or idx >= len(candles):
                continue

            ts, hrows = candles[idx]
            all3 = _all3_state(hrows)

            for horizon in HORIZONS:
                r = hrows.get(horizon)
                if not r:
                    continue
                out.append({
                    "event_id": event_id,
                    "session_date": session,
                    "from_state": event["from_state"],
                    "to_state": target,
                    "transition_timestamp": event["transition_timestamp"],
                    "offset_minutes": offset_minutes,
                    "timestamp": ts,
                    "all3_state": all3,
                    "horizon": horizon,
                    "ce_delta": r.get("ce_delta"),
                    "pe_delta": r.get("pe_delta"),
                    "delta_pattern": r.get("delta_pattern"),
                    "change_pcr": r.get("change_pcr"),
                    "change_pcr_mechanics": r.get("change_pcr_mechanics"),
                    "mechanics_score_for_target": _directional_mechanics_score(r, target),
                    "oi_imbalance": r.get("oi_imbalance"),
                    "regular_pcr_change": r.get("regular_pcr_change"),
                    "existing_horizon_state": r.get("existing_horizon_state"),
                    "futures_oi_direction": r.get("futures_oi_direction"),
                    "futures_oi_status": r.get("futures_oi_status"),
                    "vwap_side": r.get("vwap_side"),
                    "session_pcr_change": r.get("session_pcr_change"),
                    "evaluation_label": r.get("evaluation_label"),
                })

    return out


def _event_summary(window_rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    summary_events = []

    for event_id, event in enumerate(events, start=1):
        erows = [r for r in window_rows if r["event_id"] == event_id]

        pre_support = {}
        first_pre_support = {}
        for horizon in HORIZONS:
            hrs = [r for r in erows if r["horizon"] == horizon and r["offset_minutes"] < 0]
            hrs.sort(key=lambda r: r["offset_minutes"])
            supportive = [r for r in hrs if (r["mechanics_score_for_target"] or 0) > 0]
            pre_support[horizon] = len(supportive)
            first_pre_support[horizon] = (
                supportive[0]["offset_minutes"] if supportive else None
            )

        at_flip = {
            h: next(
                (
                    r["mechanics_score_for_target"]
                    for r in erows
                    if r["horizon"] == h and r["offset_minutes"] == 0
                ),
                None,
            )
            for h in HORIZONS
        }

        summary_events.append({
            "event_id": event_id,
            "session_date": event["session_date"],
            "transition_timestamp": event["transition_timestamp"],
            "from_state": event["from_state"],
            "to_state": event["to_state"],
            "pre_target_support_counts": pre_support,
            "first_pre_target_support_minutes": first_pre_support,
            "mechanics_score_at_flip": at_flip,
        })

    # "Early warning" here is intentionally descriptive:
    # target-supportive mechanics in the pre-window while all-3 has not yet flipped.
    lead_counts = {
        h: sum(
            1
            for e in summary_events
            if e["first_pre_target_support_minutes"][h] is not None
        )
        for h in HORIZONS
    }

    return {
        "status": "PASS",
        "model": MODEL,
        "transition_count": len(events),
        "window_offsets_minutes": list(WINDOW_OFFSETS),
        "definition": {
            "transition": "successive directional all-3 states change BULLISH_ALL_3 <-> BEARISH_ALL_3",
            "lead_measure": "target-supportive Change-PCR mechanics observed before the all-3 flip",
            "mechanics_score_role": "DESCRIPTIVE_ONLY",
            "no_strategy_rule_change": True,
        },
        "pre_flip_target_support_event_counts_by_horizon": lead_counts,
        "events": summary_events,
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
        description="Lead/lag event study for Change-PCR around frozen all-3 state transitions."
    )
    p.add_argument("--rows-csv", required=True, help="CHANGE_PCR_VALIDATION_V1 rows CSV")
    p.add_argument("--events-csv", required=True)
    p.add_argument("--window-csv", required=True)
    p.add_argument("--summary-json", required=True)
    args = p.parse_args(argv)

    rows = _load_rows(Path(args.rows_csv))
    events = detect_transitions(rows)
    windows = build_event_windows(rows, events)
    summary = _event_summary(windows, events)

    write_csv(events, Path(args.events_csv))
    write_csv(windows, Path(args.window_csv))
    out = Path(args.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
