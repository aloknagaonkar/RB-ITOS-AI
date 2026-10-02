"""Read-only, exact five-contract Midpoint option observation.

Market acquisition is separate from the strategy worker. The saved source tape
contains actual provider option minutes; projections never request future data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from market_lab.domain import IST
from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from market_lab.hilega_milega_pe_option_candidate_v1 import build_bearish_pe_candidate_set
from market_lab.live_option_minute_source_v1 import validate_option_minute


def _time(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ValueError("NAIVE_OPTION_OR_AUDIT_TIMESTAMP")
    return ts.astimezone(IST).replace(second=0, microsecond=0)


def create_tape(entry: dict[str, Any], terminal: dict[str, Any] | None, *,
                expiry: date, contracts: list[dict], option_minutes) -> dict[str, Any]:
    """Freeze identities at entry and acquire only exact provider observations.

    The Midpoint event labels a completed 1m close. The first causal option
    observation is the next minute OPEN, matching Hilega's boundary convention.
    Failed acquisition is recorded as unavailable, never filled or interpolated.
    """
    direction = entry.get("direction")
    if entry.get("event_type") not in {
        "A_ENTRY", "B_ENTRY", "E_ENTRY", "B_REARM_ENTRY", "E_REARM_ENTRY",
        "PM_B_ENTRY", "PM_E_ENTRY",
    } or direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("ENTRY_EVENT_REQUIRED")
    if entry.get("underlying_price") is None:
        raise ValueError("ENTRY_SPOT_REQUIRED")
    builder = build_bullish_ce_candidate_set if direction == "BULLISH" else build_bearish_pe_candidate_set
    candidate_set = builder(signal_spot=float(entry["underlying_price"]), expiry=expiry,
                            contracts=contracts, strike_step=50.0, wings=2)
    boundary = _time(entry["event_timestamp"]) + timedelta(minutes=1)
    exit_boundary = _time(terminal["event_timestamp"]) + timedelta(minutes=1) if terminal else None
    legs = []
    for candidate in candidate_set.candidates:
        leg = {"relation_to_atm": candidate.relation_to_atm, "strike": candidate.strike,
               "side": candidate.side, "expiry": candidate.expiry,
               "instrument_key": candidate.instrument_key, "minutes": [], "issue": None}
        try:
            rows = option_minutes(candidate.instrument_key)
            seen = set()
            for row in rows:
                ts = row.timestamp.astimezone(IST).replace(second=0, microsecond=0)
                if ts < boundary or (exit_boundary is not None and ts > exit_boundary):
                    continue
                if ts in seen:
                    raise ValueError("DUPLICATE_OPTION_MINUTE")
                seen.add(ts)
                health = validate_option_minute(row, expected_instrument_key=candidate.instrument_key,
                                                previous_timestamp=None)
                if not health.allowed:
                    raise ValueError(health.reason or health.state)
                leg["minutes"].append({"timestamp": ts.isoformat(), "open": float(row.open),
                                       "high": float(row.high), "low": float(row.low),
                                       "close": float(row.close)})
            leg["minutes"].sort(key=lambda r: r["timestamp"])
        except Exception as exc:
            leg["minutes"] = []
            leg["issue"] = f"{type(exc).__name__}:{exc}"
        legs.append(leg)
    return {"model": "MIDPOINT_EXACT_OPTION_TAPE_V1", "session_date": entry["session_date"],
            "entry_event_id": entry["event_id"], "entry_timestamp": entry["event_timestamp"],
            "entry_boundary": boundary.isoformat(), "terminal_event_id": terminal.get("event_id") if terminal else None,
            "exit_boundary": exit_boundary.isoformat() if exit_boundary else None,
            "direction": direction, "side": "CE" if direction == "BULLISH" else "PE",
            "expiry": expiry.isoformat(), "atm": candidate_set.atm,
            "candidate_status": candidate_set.status, "candidate_issue": candidate_set.issue,
            "legs": legs, "observation_only": True, "execution_enabled": False,
            "paper_order_enabled": False, "quantity": None}


def project_tape(tape: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Project one event/minute without looking past that decision timestamp."""
    cutoff = _time(as_of)
    entry = _time(tape["entry_boundary"])
    exit_at = _time(tape["exit_boundary"]) if tape.get("exit_boundary") else None
    output = {k: v for k, v in tape.items() if k != "legs"}
    output["as_of"] = cutoff.isoformat()
    output["legs"] = []
    if exit_at is not None and cutoff < exit_at:
        output["exit_boundary"] = None
        output["terminal_event_id"] = None
    if cutoff < entry:
        output["status"] = "ENTRY_PENDING"
        return output
    expected_side = tape["side"]
    for leg in tape["legs"]:
        item = {k: v for k, v in leg.items() if k != "minutes"}
        item.update({"entry_timestamp": entry.isoformat(), "entry_premium": None,
                     "latest_timestamp": None, "latest_premium": None, "exit_timestamp": None,
                     "exit_premium": None, "pnl_points": None, "pnl_pct": None,
                     "mfe_points": None, "mae_points": None, "status": "UNAVAILABLE"})
        if leg["side"] != expected_side or leg.get("issue"):
            item["issue"] = item.get("issue") or "OPTION_SIDE_MISMATCH"
            output["legs"].append(item)
            continue
        rows = {_time(r["timestamp"]): r for r in leg["minutes"]}
        first = rows.get(entry)
        if first is None:
            item["issue"] = "EXACT_ENTRY_MINUTE_UNAVAILABLE"
            output["legs"].append(item)
            continue
        price = float(first["open"])
        if price <= 0:
            item["issue"] = "INVALID_ENTRY_PREMIUM"
            output["legs"].append(item)
            continue
        item["entry_premium"] = price
        last_completed = min(cutoff - timedelta(minutes=1), exit_at - timedelta(minutes=1) if exit_at else cutoff)
        path = []
        t = entry
        while t <= last_completed:
            if t not in rows:
                item["issue"] = f"EXACT_OPTION_MINUTE_MISSING:{t.isoformat()}"
                break
            path.append(rows[t])
            t += timedelta(minutes=1)
        if path:
            last = path[-1]
            item["latest_timestamp"] = _time(last["timestamp"]).isoformat()
            item["latest_premium"] = float(last["close"])
            item["mfe_points"] = max(float(r["high"]) for r in path) - price
            item["mae_points"] = min(float(r["low"]) for r in path) - price
        if exit_at and cutoff >= exit_at:
            exact_exit = rows.get(exit_at)
            if exact_exit is None:
                item["status"] = "EXIT_PENDING"
                item["issue"] = item.get("issue") or "EXACT_EXIT_MINUTE_UNAVAILABLE"
            else:
                item["exit_timestamp"] = exit_at.isoformat()
                item["exit_premium"] = float(exact_exit["open"])
                item["latest_timestamp"] = exit_at.isoformat()
                item["latest_premium"] = item["exit_premium"]
                item["status"] = "CLOSED" if not item.get("issue") else "INCOMPLETE"
        else:
            item["status"] = "ACTIVE" if not item.get("issue") else "INCOMPLETE"
        if item["latest_premium"] is not None and not item.get("issue"):
            item["pnl_points"] = item["latest_premium"] - price
            item["pnl_pct"] = (item["latest_premium"] / price - 1) * 100
        output["legs"].append(item)
    output["status"] = ("AVAILABLE" if len(output["legs"]) == 5 and
                        {x["relation_to_atm"] for x in output["legs"]} == {-2,-1,0,1,2} and
                        all(x["status"] in {"ACTIVE", "CLOSED"} for x in output["legs"])
                        else "UNAVAILABLE")
    return output
