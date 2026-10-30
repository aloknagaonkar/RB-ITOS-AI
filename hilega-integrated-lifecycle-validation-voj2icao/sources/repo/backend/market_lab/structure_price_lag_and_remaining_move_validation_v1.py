from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

MODEL = "STRUCTURE_PRICE_LAG_AND_REMAINING_MOVE_VALIDATION_V1"
HORIZONS = ("5m", "10m", "15m")
BULL = "BULLISH_ALL_3"
BEAR = "BEARISH_ALL_3"
DIRS = {BULL, BEAR}
POINT_TARGETS = (20, 30, 40, 50, 75, 100)
FORWARD_WINDOWS = ((5, 1), (10, 2), (15, 3), (30, 6), (60, 12))


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first_num(row, *keys):
    for k in keys:
        if k in row:
            v = _num(row.get(k))
            if v is not None:
                return v
    return None


def _all3(hrows):
    states = [hrows.get(h, {}).get("existing_horizon_state") for h in HORIZONS]
    if any(s in (None, "", "NA") for s in states):
        return "INCOMPLETE"
    if all(s == "BULLISH" for s in states):
        return BULL
    if all(s == "BEARISH" for s in states):
        return BEAR
    return "MIXED"


def load_states(path):
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    grouped = {}
    for r in rows:
        grouped.setdefault((r["session_date"], r["timestamp"]), {})[r["horizon"]] = r

    by = defaultdict(list)
    for (d, ts), hrows in grouped.items():
        by[d].append({"timestamp": ts, "state": _all3(hrows)})
    for d in by:
        by[d].sort(key=lambda x: x["timestamp"])
    return dict(by)


def load_audits(paths):
    out = {}
    for p in paths:
        data = json.loads(Path(p).read_text())
        out[data["session_date"]] = {
            r["timestamp"]: r for r in data.get("rows", [])
        }
    return out


def direction_sign(state):
    return 1.0 if state == BULL else -1.0


def direction_name(state):
    return "BULLISH" if state == BULL else "BEARISH"


def target_signed_delta(start, end, state):
    a, b = _num(start), _num(end)
    if a is None or b is None:
        return None
    return (b - a) * direction_sign(state)


def _spot(audit):
    return _first_num(audit, "spot", "underlying_spot")


def futures_support(audit, state):
    v = audit.get("futures_oi_direction")
    if v in (None, "", "NA"):
        return None
    return str(v).upper() == direction_name(state)


def contiguous_run_len(states, idx):
    target = states[idx]["state"]
    n = 0
    while idx + n < len(states) and states[idx+n]["state"] == target:
        n += 1
    return n


def _forward_signed_move(states, audits_for_day, c2_index, c2_spot, state, step):
    idx = c2_index + step
    if idx >= len(states):
        return None
    future_spot = _spot(audits_for_day.get(states[idx]["timestamp"], {}))
    return target_signed_delta(c2_spot, future_spot, state)


def _window_path(states, audits_for_day, c2_index, c2_spot, state, steps):
    vals = []
    for off in range(1, steps + 1):
        idx = c2_index + off
        if idx >= len(states):
            break
        s = _spot(audits_for_day.get(states[idx]["timestamp"], {}))
        mv = target_signed_delta(c2_spot, s, state)
        if mv is not None:
            vals.append(mv)
    return vals


def _first_target_hit(states, audits_for_day, c2_index, c2_spot, state, target, run_end_idx):
    for idx in range(c2_index + 1, len(states)):
        s = _spot(audits_for_day.get(states[idx]["timestamp"], {}))
        mv = target_signed_delta(c2_spot, s, state)
        if mv is not None and mv >= target:
            candles = idx - c2_index
            return {
                "hit": True,
                "candles": candles,
                "minutes": candles * 5,
                "timestamp": states[idx]["timestamp"],
                "within_same_all3_run": idx <= run_end_idx,
            }
    return {
        "hit": False,
        "candles": None,
        "minutes": None,
        "timestamp": None,
        "within_same_all3_run": False,
    }


def build_events(states_by_session, audits):
    events = []
    event_id = 0

    for d in sorted(states_by_session):
        states = states_by_session[d]
        aday = audits.get(d, {})
        i = 0

        while i < len(states):
            st = states[i]["state"]

            if st not in DIRS:
                i += 1
                continue
            if i > 0 and states[i-1]["state"] == st:
                i += 1
                continue

            j = i - 1
            while j >= 0 and states[j]["state"] not in DIRS:
                j -= 1
            if j < 0 or states[j]["state"] == st:
                i += contiguous_run_len(states, i)
                continue

            final_len = contiguous_run_len(states, i)
            if final_len < 2:
                i += final_len
                continue

            c2_index = i + 1
            a1 = aday.get(states[i]["timestamp"], {})
            a2 = aday.get(states[c2_index]["timestamp"], {})

            if futures_support(a2, st) is not True:
                i += final_len
                continue

            event_id += 1
            c1_spot = _spot(a1)
            c2_spot = _spot(a2)
            c1_c2_move = target_signed_delta(c1_spot, c2_spot, st)

            if c1_c2_move is None:
                lag_class = "UNAVAILABLE"
            elif c1_c2_move <= 0:
                lag_class = "SPOT_LAG"
            else:
                lag_class = "SPOT_ALREADY_MOVED"

            run_end_idx = i + final_len - 1
            run_censored = (run_end_idx == len(states) - 1)

            run_end_spot = _spot(aday.get(states[run_end_idx]["timestamp"], {}))
            session_end_spot = _spot(aday.get(states[-1]["timestamp"], {}))

            move_to_run_end = target_signed_delta(c2_spot, run_end_spot, st)
            move_to_session_close = target_signed_delta(c2_spot, session_end_spot, st)

            row = {
                "event_id": event_id,
                "session_date": d,
                "direction": direction_name(st),
                "from_state": states[j]["state"],
                "to_state": st,
                "candle1_timestamp": states[i]["timestamp"],
                "confirmation_timestamp_candle2": states[c2_index]["timestamp"],
                "c1_spot": c1_spot,
                "confirmation_spot_c2": c2_spot,
                "target_signed_spot_move_c1_c2": c1_c2_move,
                "price_lag_class": lag_class,
                "c2_futures_oi_support": True,

                "final_all3_run_length_observed": final_len,
                "remaining_all3_candles_after_confirmation": max(0, final_len - 2),
                "remaining_all3_minutes_after_confirmation": max(0, final_len - 2) * 5,
                "all3_run_censored_by_session_end": run_censored,
                "observed_all3_run_end_timestamp": states[run_end_idx]["timestamp"],
                "observed_all3_run_end_spot": run_end_spot,
                "signed_move_confirmation_to_observed_all3_run_end_points": move_to_run_end,
                "signed_move_confirmation_to_session_close_points": move_to_session_close,
            }

            # Fixed forward windows + MFE/MAE.
            for mins, steps in FORWARD_WINDOWS:
                mv = _forward_signed_move(states, aday, c2_index, c2_spot, st, steps)
                row[f"signed_move_plus_{mins}m_points"] = mv
                row[f"directional_positive_plus_{mins}m"] = None if mv is None else mv > 0

                path = _window_path(states, aday, c2_index, c2_spot, st, steps)
                row[f"mfe_plus_{mins}m_points"] = max(path) if path else None
                row[f"mae_plus_{mins}m_points"] = min(path) if path else None

            # Point target reachability to session close.
            for target in POINT_TARGETS:
                hit = _first_target_hit(
                    states, aday, c2_index, c2_spot, st, target, run_end_idx
                )
                row[f"hit_{target}pt"] = hit["hit"]
                row[f"time_to_{target}pt_minutes"] = hit["minutes"]
                row[f"candles_to_{target}pt"] = hit["candles"]
                row[f"timestamp_hit_{target}pt"] = hit["timestamp"]
                row[f"hit_{target}pt_within_same_all3_run"] = hit["within_same_all3_run"]

            events.append(row)
            i += final_len

    return events


def _nums(rows, key):
    out = []
    for r in rows:
        v = _num(r.get(key))
        if v is not None:
            out.append(v)
    return out


def _mean(rows, key):
    v = _nums(rows, key)
    return None if not v else mean(v)


def _median(rows, key):
    v = _nums(rows, key)
    return None if not v else median(v)


def _bool_rate(rows, key):
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    return None if not vals else sum(x is True for x in vals) / len(vals)


def summary_for(rows):
    result = {
        "rows": len(rows),
        "mean_remaining_all3_candles_after_confirmation": _mean(
            rows, "remaining_all3_candles_after_confirmation"
        ),
        "median_remaining_all3_candles_after_confirmation": _median(
            rows, "remaining_all3_candles_after_confirmation"
        ),
        "mean_signed_move_to_observed_all3_run_end_points": _mean(
            rows, "signed_move_confirmation_to_observed_all3_run_end_points"
        ),
        "median_signed_move_to_observed_all3_run_end_points": _median(
            rows, "signed_move_confirmation_to_observed_all3_run_end_points"
        ),
        "mean_signed_move_to_session_close_points": _mean(
            rows, "signed_move_confirmation_to_session_close_points"
        ),
        "median_signed_move_to_session_close_points": _median(
            rows, "signed_move_confirmation_to_session_close_points"
        ),
        "censored_all3_run_count": sum(
            r.get("all3_run_censored_by_session_end") is True for r in rows
        ),
    }

    for mins, _ in FORWARD_WINDOWS:
        result[f"positive_rate_plus_{mins}m"] = _bool_rate(
            rows, f"directional_positive_plus_{mins}m"
        )
        result[f"mean_signed_move_plus_{mins}m_points"] = _mean(
            rows, f"signed_move_plus_{mins}m_points"
        )
        result[f"median_signed_move_plus_{mins}m_points"] = _median(
            rows, f"signed_move_plus_{mins}m_points"
        )
        result[f"median_mfe_plus_{mins}m_points"] = _median(
            rows, f"mfe_plus_{mins}m_points"
        )
        result[f"median_mae_plus_{mins}m_points"] = _median(
            rows, f"mae_plus_{mins}m_points"
        )

    for target in POINT_TARGETS:
        result[f"hit_{target}pt_rate"] = _bool_rate(rows, f"hit_{target}pt")
        hit_rows = [r for r in rows if r.get(f"hit_{target}pt") is True]
        result[f"median_time_to_{target}pt_minutes_if_hit"] = _median(
            hit_rows, f"time_to_{target}pt_minutes"
        )
        result[f"hit_{target}pt_within_same_all3_run_rate"] = _bool_rate(
            rows, f"hit_{target}pt_within_same_all3_run"
        )

    return result


def by_lag(rows):
    return {
        "SPOT_LAG": summary_for([r for r in rows if r["price_lag_class"] == "SPOT_LAG"]),
        "SPOT_ALREADY_MOVED": summary_for([
            r for r in rows if r["price_lag_class"] == "SPOT_ALREADY_MOVED"
        ]),
        "UNAVAILABLE": summary_for([
            r for r in rows if r["price_lag_class"] == "UNAVAILABLE"
        ]),
    }


def build_report(events):
    bullish = [r for r in events if r["direction"] == "BULLISH"]
    bearish = [r for r in events if r["direction"] == "BEARISH"]

    return {
        "status": "PASS",
        "model": MODEL,
        "role": "INDEPENDENT_VALIDATION_DESCRIPTIVE_ONLY",
        "strategy_logic_changed": False,
        "all3_state_definition_changed": False,
        "threshold_optimization": False,
        "frozen_structural_gate": (
            "new opposite-direction ALL3 run survives to candle 2 and "
            "candle-2 futures OI direction supports target direction"
        ),
        "frozen_price_lag_definition": (
            "SPOT_LAG iff target-signed spot move candle1->candle2 <= 0; "
            "SPOT_ALREADY_MOVED iff > 0"
        ),
        "point_targets_points": list(POINT_TARGETS),
        "forward_windows_minutes": [m for m, _ in FORWARD_WINDOWS],
        "research_questions": [
            "Does SPOT_LAG outperform SPOT_ALREADY_MOVED after structural confirmation?",
            "How many same-direction ALL3 candles remain after confirmation?",
            "How much directional NIFTY movement remains after confirmation?",
            "How often are +20/+30/+40/+50/+75/+100 point targets reached, and how quickly?",
            "Are point targets reached while the same ALL3 run is still active?",
        ],
        "notes": [
            "Point targets are descriptive bins, not trading thresholds.",
            "Observed ALL3 runs reaching session end are marked censored.",
            "Run-end movement is therefore 'to observed run end' when censored.",
            "Session-close and fixed-horizon movement remain fully observable when data exists.",
            "This is NIFTY underlying research, not option-premium PnL.",
            "Do not assume 50 NIFTY points equals 25 premium points; exact option replay comes later.",
        ],
        "event_count": len(events),
        "all_events": summary_for(events),
        "by_price_lag": by_lag(events),
        "by_direction": {
            "BULLISH": {
                "all": summary_for(bullish),
                "by_price_lag": by_lag(bullish),
            },
            "BEARISH": {
                "all": summary_for(bearish),
                "by_price_lag": by_lag(bearish),
            },
        },
        "events": events,
    }


def write_csv(events, path):
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

    states = load_states(a.rows_csv)
    audits = load_audits(a.audit_json)
    events = build_events(states, audits)
    report = build_report(events)

    write_csv(events, a.events_csv)
    out = Path(a.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
