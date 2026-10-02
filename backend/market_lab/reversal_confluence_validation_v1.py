from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

MODEL = "REVERSAL_CONFLUENCE_VALIDATION_V1"
HORIZONS = ("5m", "10m", "15m")
BULL = "BULLISH_ALL_3"
BEAR = "BEARISH_ALL_3"
DIR_STATES = {BULL, BEAR}


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _support_sign(value, target):
    v = _num(value)
    if v is None or v == 0:
        return None
    if target == BULL:
        return v > 0
    return v < 0


def _support_text(value, target_direction):
    if value in (None, "", "NA"):
        return None
    return str(value).upper() == target_direction


def _all3_from_hrows(hrows):
    states = [hrows.get(h, {}).get("existing_horizon_state") for h in HORIZONS]
    if any(s in (None, "", "NA") for s in states):
        return "INCOMPLETE"
    if all(s == "BULLISH" for s in states):
        return BULL
    if all(s == "BEARISH" for s in states):
        return BEAR
    return "MIXED"


def load_state_rows(path):
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    grouped = {}
    for r in rows:
        grouped.setdefault((r["session_date"], r["timestamp"]), {})[r["horizon"]] = r
    by_session = defaultdict(list)
    for (d, ts), hrows in grouped.items():
        by_session[d].append({"timestamp": ts, "state": _all3_from_hrows(hrows)})
    for d in by_session:
        by_session[d].sort(key=lambda x: x["timestamp"])
    return dict(by_session)


def load_audits(paths):
    by_session = {}
    for p in paths:
        data = json.loads(Path(p).read_text())
        d = data.get("session_date")
        rows = data.get("rows", [])
        by_session[d] = {r["timestamp"]: r for r in rows}
    return by_session


def _contiguous_run_len(states, idx, direction, step):
    n = 0
    j = idx
    while 0 <= j < len(states) and states[j]["state"] == direction:
        n += 1
        j += step
    return n


def _next_directional_index(states, idx):
    for j in range(idx + 1, len(states)):
        if states[j]["state"] in DIR_STATES:
            return j
    return None


def build_transition_events(state_by_session, audit_by_session):
    events = []
    event_id = 0
    for d in sorted(state_by_session):
        states = state_by_session[d]
        # A transition starts at the first target-direction ALL3 candle after the
        # most recent opposite directional ALL3 observation. MIXED/INCOMPLETE
        # candles may sit between the two and are retained as a gap measure.
        last_dir_idx = None
        for i, row in enumerate(states):
            if row["state"] not in DIR_STATES:
                continue
            if last_dir_idx is None:
                last_dir_idx = i
                continue
            prev = states[last_dir_idx]
            if prev["state"] == row["state"]:
                last_dir_idx = i
                continue

            event_id += 1
            target = row["state"]
            source = prev["state"]
            target_dir = "BULLISH" if target == BULL else "BEARISH"
            audit = audit_by_session.get(d, {}).get(row["timestamp"], {})

            # Actual contiguous persistence around the transition.
            prior_run = _contiguous_run_len(states, last_dir_idx, source, -1)
            resulting_run = _contiguous_run_len(states, i, target, +1)
            gap_candles = max(0, i - last_dir_idx - 1)

            sess_imb_support = _support_sign(audit.get("session_imbalance"), target)
            sess_pcr_support = _support_sign(audit.get("session_pcr_change_0920_to_now"), target)
            if sess_imb_support is True and sess_pcr_support is True:
                session_option_context = True
            elif sess_imb_support is False and sess_pcr_support is False:
                session_option_context = False
            else:
                session_option_context = None

            futures_support = _support_text(audit.get("futures_oi_direction"), target_dir)
            vwap_support = _support_text(
                audit.get("vwap_side"),
                "ABOVE" if target == BULL else "BELOW",
            )
            p1_support = _support_text(audit.get("strategy_p1"), target_dir)
            p2_support = _support_text(audit.get("strategy_p2_confirmed"), target_dir)

            supports = {
                "session_option_context_support": session_option_context,
                "futures_oi_support": futures_support,
                "vwap_support": vwap_support,
                "strategy_p1_support": p1_support,
                "strategy_p2_support": p2_support,
            }
            available = sum(v is not None for v in supports.values())
            positive = sum(v is True for v in supports.values())

            if resulting_run == 1:
                bucket = "ONE_CANDLE"
            elif resulting_run == 2:
                bucket = "TWO_CANDLE"
            else:
                bucket = "THREE_PLUS"

            events.append({
                "event_id": event_id,
                "session_date": d,
                "transition_timestamp": row["timestamp"],
                "from_state": source,
                "to_state": target,
                "gap_candles": gap_candles,
                "prior_contiguous_run_length": prior_run,
                "resulting_run_length": resulting_run,
                "resulting_run_bucket": bucket,
                "spot": audit.get("spot"),
                "moving_atm": audit.get("moving_atm"),
                "session_imbalance": audit.get("session_imbalance"),
                "session_pcr_change": audit.get("session_pcr_change_0920_to_now"),
                "session_option_context_support": session_option_context,
                "futures_oi_status": audit.get("futures_oi_status"),
                "futures_oi_direction": audit.get("futures_oi_direction"),
                "futures_oi_streak": (
                    audit.get("bullish_oi_status_streak")
                    if target == BULL else audit.get("bearish_oi_status_streak")
                ),
                "futures_oi_support": futures_support,
                "vwap": audit.get("vwap"),
                "vwap_distance": audit.get("vwap_distance"),
                "vwap_side": audit.get("vwap_side"),
                "vwap_support": vwap_support,
                "strategy_events": audit.get("strategy_events"),
                "strategy_p1": audit.get("strategy_p1"),
                "strategy_p1_support": p1_support,
                "strategy_p2_confirmed": audit.get("strategy_p2_confirmed"),
                "strategy_p2_support": p2_support,
                "evaluation_label": audit.get("evaluation_label"),
                "available_confluence_components": available,
                "supportive_confluence_components": positive,
            })
            last_dir_idx = i
    return events


def _summarize_group(events):
    if not events:
        return {"events": 0}
    scores = [e["supportive_confluence_components"] for e in events]
    available = [e["available_confluence_components"] for e in events]
    return {
        "events": len(events),
        "mean_supportive_components": mean(scores),
        "median_supportive_components": median(scores),
        "mean_available_components": mean(available),
        "mean_resulting_run_length": mean(e["resulting_run_length"] for e in events),
        "median_resulting_run_length": median(e["resulting_run_length"] for e in events),
        "mean_prior_run_length": mean(e["prior_contiguous_run_length"] for e in events),
        "session_option_context_support_rate_available": _rate(events, "session_option_context_support"),
        "futures_oi_support_rate_available": _rate(events, "futures_oi_support"),
        "vwap_support_rate_available": _rate(events, "vwap_support"),
        "strategy_p1_support_rate_available": _rate(events, "strategy_p1_support"),
        "strategy_p2_support_rate_available": _rate(events, "strategy_p2_support"),
    }


def _rate(events, key):
    vals = [e[key] for e in events if e[key] is not None]
    return None if not vals else sum(v is True for v in vals) / len(vals)


def build_report(events):
    by_bucket = {}
    for bucket in ("ONE_CANDLE", "TWO_CANDLE", "THREE_PLUS"):
        by_bucket[bucket] = _summarize_group([e for e in events if e["resulting_run_bucket"] == bucket])

    by_direction = {}
    for state in (BULL, BEAR):
        by_direction[state] = _summarize_group([e for e in events if e["to_state"] == state])

    score_dist = Counter(
        (e["available_confluence_components"], e["supportive_confluence_components"])
        for e in events
    )

    return {
        "status": "PASS",
        "model": MODEL,
        "role": "DESCRIPTIVE_RESEARCH_ONLY",
        "strategy_logic_changed": False,
        "all3_state_definition_changed": False,
        "threshold_optimization": False,
        "event_definition": (
            "first opposite-direction ALL3 candle after the most recent directional ALL3 observation; "
            "MIXED/INCOMPLETE gap is measured, not discarded"
        ),
        "outcome": (
            "resulting contiguous ALL3 run length; ONE_CANDLE/TWO_CANDLE/THREE_PLUS buckets are descriptive only"
        ),
        "confluence_components": [
            "fixed-session option OI/PCR context",
            "futures OI direction",
            "VWAP side",
            "existing strategy P1 direction when available",
            "existing strategy P2-confirmed direction when available",
        ],
        "notes": [
            "The new ALL3 direction itself is the event definition and is not counted as confluence.",
            "No minimum confluence score is proposed.",
            "No component weights are fitted.",
            "Missing strategy-event fields remain unavailable rather than counted against the event.",
            "Change-PCR is intentionally excluded from the confluence score because expansion validation was noisy.",
        ],
        "event_count": len(events),
        "by_resulting_run_bucket": by_bucket,
        "by_target_direction": by_direction,
        "confluence_score_distribution": [
            {
                "available_components": k[0],
                "supportive_components": k[1],
                "events": v,
            }
            for k, v in sorted(score_dist.items())
        ],
        "events": events,
    }


def write_events_csv(events, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        p.write_text("")
        return
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0].keys()))
        w.writeheader()
        w.writerows(events)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-csv", required=True)
    ap.add_argument("--audit-json", action="append", required=True)
    ap.add_argument("--events-csv", required=True)
    ap.add_argument("--summary-json", required=True)
    a = ap.parse_args(argv)

    state_by_session = load_state_rows(a.rows_csv)
    audit_by_session = load_audits(a.audit_json)
    events = build_transition_events(state_by_session, audit_by_session)
    report = build_report(events)

    write_events_csv(events, a.events_csv)
    out = Path(a.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
