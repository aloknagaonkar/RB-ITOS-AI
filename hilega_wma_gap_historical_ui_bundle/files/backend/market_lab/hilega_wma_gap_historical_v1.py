"""Read-only historical presentation for the tested Hilega WMA-gap candidate."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path("data/historical-evidence/hilega-wma-gap-490-v1")
RESULTS = ROOT / "trade-results.csv"
ATTEMPTS = ROOT / "confirmation-attempts.csv"
STRATEGY_ID = "HILEGA_WMA_GAP_V2_REPLAY"
STRATEGY_VERSION = "wma-gap-v1"


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _metrics(strategy_id: str, values: list[float], *, signals: int,
             entries: int, denied: int, available: bool = True) -> dict[str, Any]:
    gains = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    flat = [value for value in values if value == 0]
    gross_gain = sum(gains)
    gross_loss = abs(sum(losses))
    completed = len(values)
    return {
        "strategy_id": strategy_id,
        "available": available,
        "signals": signals,
        "entries": entries,
        "denied": denied,
        "completed": completed,
        "winning_trades": len(gains),
        "losing_trades": len(losses),
        "breakeven_trades": len(flat),
        "gross_points_gained": gross_gain,
        "gross_points_lost": gross_loss,
        "net_points": gross_gain - gross_loss,
        "trade_win_loss_ratio": len(gains) / len(losses) if losses else None,
        "gain_loss_ratio": gross_gain / gross_loss if gross_loss else None,
        "win_rate_pct": 100.0 * len(gains) / completed if completed else None,
    }


def _step(label: str, status: str, value: Any, requirement: str,
          explanation: str) -> dict[str, Any]:
    return {
        "label": label,
        "status": status,
        "value": value,
        "requirement": requirement,
        "explanation": explanation,
    }


def _report(checkpoint: str, trade: dict[str, str], *, event: str,
            state_before: str, state_after: str, close: float | None,
            steps: list[dict[str, Any]], attempt: dict[str, str] | None = None,
            points: float | None = None) -> dict[str, Any]:
    direction = str(trade.get("direction") or "")
    accepted = event not in {"WMA_GAP_WAIT", "WMA_GAP_NO_ENTRY_BY_T10"}
    transition = {
        "event_type": event,
        "event_time": checkpoint,
        "price": close,
        "entry_price": close if event == "WMA_GAP_ENTRY" else None,
        "points": points,
        "source": STRATEGY_ID,
        "state_before": state_before,
        "state_after": state_after,
        "details": {"trade_id": trade.get("trade_id")},
    }
    return {
        "checkpoint": checkpoint,
        "linked_signal_bar": trade.get("entry_timestamp"),
        "bar": {"open": None, "high": None, "low": None, "close": close, "volume": None},
        "indicators": {
            "rsi9": _number((attempt or {}).get("confirmation_rsi9")),
            "ema3_rsi": _number((attempt or {}).get("confirmation_ema3_rsi")),
            "wma21_rsi": _number((attempt or {}).get("confirmation_wma21_rsi")),
        },
        "conditions": {
            "strategy_steps": steps,
            "directional_wma_change": _number((attempt or {}).get("confirmation_wma_strength")),
            "directional_gap": _number((attempt or {}).get("confirmation_directional_gap")),
            "directional_gap_delta": _number((attempt or {}).get("directional_gap_delta")),
            "failure_reasons": str((attempt or {}).get("failure_reasons") or "").split("|") if attempt else [],
        },
        "strategy": {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "direction": direction,
            "directional_action": event,
            "state_before": state_before,
            "state_after": state_after,
            "owner_before": direction if state_before == "ACTIVE" else "NONE",
            "owner_after": direction if state_after == "ACTIVE" else "NONE",
            "events_emitted": [event],
            "selected_route": trade.get("route"),
            "decision_authoritative": True,
            "accepted": accepted,
        },
        "route_a": {}, "route_b": {}, "transitions": [transition],
        "option_candidate": None, "option_market_snapshot": None,
        "option_lifecycle": {},
        "audit_integrity": {
            "source": "IMMUTABLE_WMA_GAP_490_RESEARCH_ARTIFACT",
            "canonical_step_audit_available": True,
            "trade_id": trade.get("trade_id"),
        },
        "safety": {"observation_only": True, "execution_enabled": False,
                   "paper_order_enabled": False, "quantity": None},
    }


def recorded_live_metrics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Pair authoritative recorded entry/exit transitions without synthesizing."""
    active: dict[str, float] = {}
    values: list[float] = []
    seen: set[tuple[str, str, str]] = set()
    signals = 0
    for report in sorted(reports, key=lambda row: str(row.get("checkpoint") or "")):
        for transition in report.get("transitions") or []:
            event = str(transition.get("event_type") or "").upper()
            stamp = str(transition.get("event_time") or report.get("checkpoint") or "")
            price = _number(transition.get("price") or transition.get("entry_price"))
            identity = (stamp, event, str(price))
            if identity in seen:
                continue
            seen.add(identity)
            direction = "BEARISH" if "BEARISH" in event else "BULLISH"
            is_entry = event.startswith("ENTRY_") or event.endswith("_ENTRY")
            is_exit = "EXIT" in event
            if is_entry and price is not None and direction not in active:
                active[direction] = price
                signals += 1
            elif is_exit and price is not None and direction in active:
                entry = active.pop(direction)
                values.append(price - entry if direction == "BULLISH" else entry - price)
    result = _metrics("LIVE_RECORDED_V1", values, signals=signals,
                      entries=signals, denied=0, available=bool(signals))
    if active:
        result["unresolved"] = len(active)
    if not signals:
        result["unavailable_reason"] = "No authoritative recorded live entry/exit lifecycle was available for this date."
    return result


def build_wma_gap_session(session_date: str, root: Path = ROOT) -> dict[str, Any]:
    trades = [row for row in _rows(root / RESULTS.name)
              if row.get("session_date") == session_date]
    if not trades:
        raise FileNotFoundError(session_date)
    attempts_by_trade: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows(root / ATTEMPTS.name):
        if row.get("session_date") == session_date:
            attempts_by_trade[str(row.get("trade_id"))].append(row)

    reports: list[dict[str, Any]] = []
    canonical_values: list[float] = []
    candidate_values: list[float] = []
    for trade in trades:
        trade_id = str(trade.get("trade_id"))
        signal = str(trade.get("entry_timestamp") or "")
        direction = str(trade.get("direction") or "")
        canonical = _number(trade.get("canonical_points"))
        if canonical is not None:
            canonical_values.append(canonical)
        base_steps = [
            _step("Canonical Hilega signal", "PASS", direction,
                  "BULLISH or BEARISH canonical signal", "Starts the T+10 observation window; no candidate entry yet."),
            _step("Directional WMA21 strength", "WAIT", None,
                  ">= 0.75", "Checked on every completed one-minute candle."),
            _step("Later one-minute persistence", "WAIT", None,
                  "A later consecutive completed minute", "The WMA arm candle cannot confirm itself."),
            _step("Directional EMA3-WMA21 gap", "WAIT", None,
                  "Positive and expanding", "Bullish uses EMA-WMA; bearish uses WMA-EMA."),
        ]
        reports.append(_report(signal, trade, event="WMA_GAP_SIGNAL_RECEIVED",
                               state_before="IDLE", state_after="WAITING_FOR_WMA_ARM",
                               close=_number(trade.get("entry_price")), steps=base_steps))
        attempts = sorted(attempts_by_trade.get(trade_id, []),
                          key=lambda row: str(row.get("confirmation_timestamp") or ""))
        for attempt in attempts:
            passed = _bool(attempt.get("passed"))
            strength = _number(attempt.get("confirmation_wma_strength"))
            gap = _number(attempt.get("confirmation_directional_gap"))
            delta = _number(attempt.get("directional_gap_delta"))
            steps = [
                _step("Canonical Hilega signal", "PASS", direction, "Canonical directional signal", "Signal identity is unchanged."),
                _step("WMA21 arm", "PASS" if (_number(attempt.get("armed_wma_strength")) or 0) >= .75 else "FAIL", _number(attempt.get("armed_wma_strength")), ">= 0.75", "Directional WMA strength on the prior minute."),
                _step("WMA21 persistence", "PASS" if _bool(attempt.get("threshold_maintained")) else "FAIL", strength, ">= 0.75", "Threshold must remain valid on this later minute."),
                _step("Directional gap positive", "PASS" if _bool(attempt.get("directional_gap_positive")) else "FAIL", gap, "> 0", "Direction-normalized EMA3-WMA21 separation."),
                _step("Directional gap expanding", "PASS" if _bool(attempt.get("directional_gap_expanding")) else "FAIL", delta, "> 0 vs previous minute", "Rejects a contracting confirmation."),
            ]
            reports.append(_report(str(attempt.get("confirmation_timestamp")), trade,
                                   event="WMA_GAP_ENTRY" if passed else "WMA_GAP_WAIT",
                                   state_before="WAITING_FOR_CONFIRMATION",
                                   state_after="ACTIVE" if passed else "WAITING_FOR_CONFIRMATION",
                                   close=_number(attempt.get("confirmation_close")),
                                   steps=steps, attempt=attempt))
        entered = str(trade.get("candidate_decision")) == "ENTRY"
        if entered:
            value = _number(trade.get("candidate_points"))
            if value is not None:
                candidate_values.append(value)
            reports.append(_report(str(trade.get("exit_timestamp")), trade,
                                   event="WMA_GAP_CANONICAL_EXIT",
                                   state_before="ACTIVE", state_after="CLOSED",
                                   close=_number(trade.get("exit_price")), steps=[
                                       _step("Entry confirmed", "PASS", trade.get("candidate_entry_timestamp"), "WMA arm + later positive expanding gap", "Candidate entered at the confirmation close."),
                                       _step("Exit policy", "PASS", value, "Unchanged canonical v1 exit", "No experimental exit rule is applied."),
                                   ], points=value))
        else:
            reports.append(_report(str(trade.get("exit_timestamp")), trade,
                                   event="WMA_GAP_NO_ENTRY_BY_T10",
                                   state_before="WAITING_FOR_CONFIRMATION", state_after="DENIED",
                                   close=_number(trade.get("exit_price")), steps=[
                                       _step("Confirmation deadline", "FAIL", "NO_ENTRY_BY_T10", "Confirm within 10 minutes", "Signal was denied; it is not counted as a zero-point trade."),
                                   ]))

    reports.sort(key=lambda row: (str(row["checkpoint"]), str(row["audit_integrity"].get("trade_id"))))
    v1 = _metrics("HILEGA_V1_REPLAY", canonical_values, signals=len(trades),
                  entries=len(trades), denied=0)
    candidate = _metrics(STRATEGY_ID, candidate_values, signals=len(trades),
                         entries=len(candidate_values), denied=len(trades) - len(candidate_values))
    live = _metrics("LIVE_RECORDED_V1", [], signals=0, entries=0, denied=0,
                    available=False)
    live["unavailable_reason"] = "Recorded live metrics are not substituted with replay outcomes."
    return {
        "session_date": session_date,
        "source": "WMA_GAP_490_RESEARCH",
        "source_id": f"wma-gap:{session_date}",
        "evidence_level": "STRATEGY",
        "ce_available": False,
        "manifest": {}, "audit_chain_ok": None,
        "audit_chain_issue": "Research artifacts are read-only; they are not the live hash-chain audit.",
        "reports": reports, "report_count": len(reports),
        "strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION,
        "performance_summary": [live, v1, candidate],
        "comparison": {
            "candidate_net_delta_vs_v1": candidate["net_points"] - v1["net_points"],
            "losses_avoided": sum(1 for row in trades if row.get("candidate_decision") != "ENTRY" and (_number(row.get("canonical_points")) or 0) < 0),
            "winners_denied": sum(1 for row in trades if row.get("candidate_decision") != "ENTRY" and (_number(row.get("canonical_points")) or 0) > 0),
        },
        "observation_only": True, "execution_enabled": False,
        "warning": "Tested WMA-gap replay from immutable historical artifacts. Live strategy, orders and quantity are unchanged.",
    }
