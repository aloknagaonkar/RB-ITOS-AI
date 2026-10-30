from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

MODEL = "POST_CONFIRMATION_PRICE_IMPULSE_VALIDATION_V1"
HORIZONS = ("5m", "10m", "15m")
BULL = "BULLISH_ALL_3"
BEAR = "BEARISH_ALL_3"
DIRS = {BULL, BEAR}


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
        out[data["session_date"]] = {r["timestamp"]: r for r in data.get("rows", [])}
    return out


def direction_sign(state):
    return 1.0 if state == BULL else -1.0


def contiguous_run_len(states, idx):
    st = states[idx]["state"]
    n = 0
    while idx + n < len(states) and states[idx + n]["state"] == st:
        n += 1
    return n


def target_signed_delta(start, end, state):
    a, b = _num(start), _num(end)
    if a is None or b is None:
        return None
    return (b - a) * direction_sign(state)


def futures_support(audit, target):
    v = audit.get("futures_oi_direction")
    if v in (None, "", "NA"):
        return None
    desired = "BULLISH" if target == BULL else "BEARISH"
    return str(v).upper() == desired


def vwap_target_distance(audit, target):
    # Prefer explicit distance when available. If signed semantics are unknown,
    # derive from futures close - VWAP so positive always means target-side.
    fc = _first_num(audit, "futures_close", "future_close")
    vw = _first_num(audit, "vwap", "futures_vwap")
    if fc is not None and vw is not None:
        raw = fc - vw
        return raw * direction_sign(target)

    # Last-resort explicit distance. Assumed close - VWAP if supplied by V1.1 audit.
    dist = _first_num(audit, "vwap_distance", "futures_vwap_distance_points")
    if dist is None:
        return None
    return dist * direction_sign(target)


def _spot(audit):
    return _first_num(audit, "spot", "underlying_spot")


def _fut_close(audit):
    return _first_num(audit, "futures_close", "future_close")


def build_events(states_by_session, audits):
    events = []
    event_id = 0

    for d in sorted(states_by_session):
        states = states_by_session[d]
        i = 0
        while i < len(states):
            st = states[i]["state"]
            if st not in DIRS:
                i += 1
                continue
            if i > 0 and states[i - 1]["state"] == st:
                i += 1
                continue

            # Most recent directional state before this run.
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

            # Frozen structural confirmation: candle 2 exists and futures aligns at candle 2.
            a1 = audits.get(d, {}).get(states[i]["timestamp"], {})
            a2 = audits.get(d, {}).get(states[i+1]["timestamp"], {})
            f2 = futures_support(a2, st)
            if f2 is not True:
                i += final_len
                continue

            event_id += 1
            c1_spot, c2_spot = _spot(a1), _spot(a2)
            c1_fut, c2_fut = _fut_close(a1), _fut_close(a2)

            spot_impulse = target_signed_delta(c1_spot, c2_spot, st)
            fut_impulse = target_signed_delta(c1_fut, c2_fut, st)

            vd1 = vwap_target_distance(a1, st)
            vd2 = vwap_target_distance(a2, st)
            vd_change = None if vd1 is None or vd2 is None else vd2 - vd1

            # Natural sign splits only; no fitted thresholds.
            spot_support = None if spot_impulse is None else spot_impulse > 0
            fut_price_support = None if fut_impulse is None else fut_impulse > 0
            vwap_target_side = None if vd2 is None else vd2 > 0
            vwap_improving = None if vd_change is None else vd_change > 0
            spot_fut_agree = None
            if spot_support is not None and fut_price_support is not None:
                spot_fut_agree = bool(spot_support and fut_price_support)

            # Evaluation-only forward signed movement from candle 2.
            forward = {}
            c2_index = i + 1
            for mins, step in ((5,1),(10,2),(15,3),(30,6)):
                idx = c2_index + step
                future_spot = None
                if idx < len(states):
                    future_spot = _spot(
                        audits.get(d, {}).get(states[idx]["timestamp"], {})
                    )
                mv = target_signed_delta(c2_spot, future_spot, st)
                forward[f"signed_spot_move_plus_{mins}m"] = mv
                forward[f"directional_positive_plus_{mins}m"] = (
                    None if mv is None else mv > 0
                )

            # 15m and 30m path MFE/MAE, evaluation-only.
            for mins, steps in ((15,3),(30,6)):
                path = []
                for off in range(1, steps + 1):
                    idx = c2_index + off
                    if idx >= len(states):
                        break
                    s = _spot(audits.get(d, {}).get(states[idx]["timestamp"], {}))
                    mv = target_signed_delta(c2_spot, s, st)
                    if mv is not None:
                        path.append(mv)
                forward[f"mfe_points_plus_{mins}m"] = max(path) if path else None
                forward[f"mae_points_plus_{mins}m"] = min(path) if path else None

            row = {
                "event_id": event_id,
                "session_date": d,
                "direction": "BULLISH" if st == BULL else "BEARISH",
                "candle1_timestamp": states[i]["timestamp"],
                "candle2_timestamp": states[i+1]["timestamp"],
                "final_all3_run_length": final_len,
                "c2_futures_oi_support": True,

                "c1_spot": c1_spot,
                "c2_spot": c2_spot,
                "target_signed_spot_impulse_c1_c2": spot_impulse,
                "spot_impulse_supportive": spot_support,

                "c1_futures_close": c1_fut,
                "c2_futures_close": c2_fut,
                "target_signed_futures_price_impulse_c1_c2": fut_impulse,
                "futures_price_impulse_supportive": fut_price_support,

                "c1_vwap_target_distance": vd1,
                "c2_vwap_target_distance": vd2,
                "vwap_target_distance_change_c1_c2": vd_change,
                "c2_vwap_target_side": vwap_target_side,
                "vwap_distance_improving": vwap_improving,

                "spot_and_futures_price_impulse_supportive": spot_fut_agree,
            }
            row.update(forward)
            events.append(row)
            i += final_len

    return events


def _vals(rows, key):
    out = []
    for r in rows:
        v = _num(r.get(key))
        if v is not None:
            out.append(v)
    return out


def _mean(rows, key):
    v = _vals(rows, key)
    return None if not v else mean(v)


def _median(rows, key):
    v = _vals(rows, key)
    return None if not v else median(v)


def _positive_rate(rows, key):
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    return None if not vals else sum(x is True for x in vals) / len(vals)


def outcome_summary(rows):
    return {
        "rows": len(rows),
        "positive_rate_plus_5m": _positive_rate(rows, "directional_positive_plus_5m"),
        "positive_rate_plus_10m": _positive_rate(rows, "directional_positive_plus_10m"),
        "positive_rate_plus_15m": _positive_rate(rows, "directional_positive_plus_15m"),
        "positive_rate_plus_30m": _positive_rate(rows, "directional_positive_plus_30m"),
        "mean_signed_move_plus_5m": _mean(rows, "signed_spot_move_plus_5m"),
        "median_signed_move_plus_5m": _median(rows, "signed_spot_move_plus_5m"),
        "mean_signed_move_plus_10m": _mean(rows, "signed_spot_move_plus_10m"),
        "median_signed_move_plus_10m": _median(rows, "signed_spot_move_plus_10m"),
        "mean_signed_move_plus_15m": _mean(rows, "signed_spot_move_plus_15m"),
        "median_signed_move_plus_15m": _median(rows, "signed_spot_move_plus_15m"),
        "mean_signed_move_plus_30m": _mean(rows, "signed_spot_move_plus_30m"),
        "median_signed_move_plus_30m": _median(rows, "signed_spot_move_plus_30m"),
        "median_mfe_points_plus_15m": _median(rows, "mfe_points_plus_15m"),
        "median_mae_points_plus_15m": _median(rows, "mae_points_plus_15m"),
        "median_mfe_points_plus_30m": _median(rows, "mfe_points_plus_30m"),
        "median_mae_points_plus_30m": _median(rows, "mae_points_plus_30m"),
    }


def split(rows, key):
    yes = [r for r in rows if r.get(key) is True]
    no = [r for r in rows if r.get(key) is False]
    na = [r for r in rows if r.get(key) is None]
    return {
        "true": outcome_summary(yes),
        "false": outcome_summary(no),
        "unavailable_rows": len(na),
    }


def direction_split(rows):
    out = {}
    for d in ("BULLISH", "BEARISH"):
        rs = [r for r in rows if r["direction"] == d]
        out[d] = {
            "all": outcome_summary(rs),
            "spot_impulse_supportive": split(rs, "spot_impulse_supportive"),
            "futures_price_impulse_supportive": split(rs, "futures_price_impulse_supportive"),
            "vwap_distance_improving": split(rs, "vwap_distance_improving"),
            "spot_and_futures_price_impulse_supportive": split(
                rs, "spot_and_futures_price_impulse_supportive"
            ),
        }
    return out


def build_report(events):
    return {
        "status": "PASS",
        "model": MODEL,
        "role": "DEVELOPMENT_COHORT_DESCRIPTIVE_RESEARCH_ONLY",
        "strategy_logic_changed": False,
        "all3_state_definition_changed": False,
        "threshold_optimization": False,
        "frozen_structural_gate": (
            "new opposite-direction ALL3 run survives to candle 2 and "
            "candle-2 futures OI direction supports target direction"
        ),
        "research_question": (
            "Within structurally confirmed candle-2 events, do causal price-impulse "
            "features available at candle 2 separate cases with better subsequent "
            "directional NIFTY movement?"
        ),
        "feature_rules": [
            "spot impulse = target-signed spot move from candle 1 to candle 2",
            "futures price impulse = target-signed futures close move from candle 1 to candle 2",
            "VWAP target distance = target-signed (futures close - VWAP)",
            "VWAP improving = target distance at candle 2 > target distance at candle 1",
            "all feature splits use natural zero/sign boundaries only",
        ],
        "evaluation_only": [
            "directional signed NIFTY spot movement after candle 2 at +5/+10/+15/+30m",
            "directional-positive rate at +5/+10/+15/+30m",
            "MFE/MAE over the next 15m and 30m",
        ],
        "notes": [
            "Use only the 54-session development cohort in this phase.",
            "Do not use the 46-session holdout outcomes to define or tune these features.",
            "No minimum point, ATR, VWAP-distance, or probability threshold is optimized.",
            "This is underlying-price research, not option-premium PnL.",
            "A later study may add ATR normalization only after the raw causal impulse behavior is understood.",
        ],
        "event_count": len(events),
        "all_confirmed_events": outcome_summary(events),
        "spot_impulse_supportive": split(events, "spot_impulse_supportive"),
        "futures_price_impulse_supportive": split(events, "futures_price_impulse_supportive"),
        "c2_vwap_target_side": split(events, "c2_vwap_target_side"),
        "vwap_distance_improving": split(events, "vwap_distance_improving"),
        "spot_and_futures_price_impulse_supportive": split(
            events, "spot_and_futures_price_impulse_supportive"
        ),
        "by_direction": direction_split(events),
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
    p = Path(a.summary_json)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
