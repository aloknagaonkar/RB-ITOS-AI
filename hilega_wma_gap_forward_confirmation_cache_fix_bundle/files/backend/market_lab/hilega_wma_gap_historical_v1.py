"""Read-only historical presentation for the tested Hilega WMA-gap candidate."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path("data/historical-evidence/hilega-wma-gap-490-v1")
FORWARD_ROOT = Path("data/historical-evidence/hilega-wma-gap-forward-confirmation-v1")
RESULTS = ROOT / "trade-results.csv"
ATTEMPTS = ROOT / "confirmation-attempts.csv"
TIMELINE = ROOT / "candidate-timeline.csv"
STRATEGY_ID = "HILEGA_WMA_GAP_V2_REPLAY"
STRATEGY_VERSION = "wma-gap-v1"


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _root_for_session(session_date: str, requested: Path | None) -> tuple[Path, str]:
    if requested is None:
        requested = ROOT
    if requested != ROOT:
        return requested, "EXPLICIT_ROOT"
    if (FORWARD_ROOT / "sessions" / session_date / "manifest.json").is_file() or any(
        row.get("session_date") == session_date
        for row in _rows(FORWARD_ROOT / RESULTS.name)
    ):
        return FORWARD_ROOT, "NEW_FORWARD_CONFIRMATION"
    return ROOT, "FROZEN_490_RESEARCH"


def _zero_trade_forward_session(session_date: str, root: Path) -> dict[str, Any] | None:
    path = root / "sessions" / session_date / "manifest.json"
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if int(manifest.get("signals") or 0) != 0:
        return None
    live = _metrics("LIVE_RECORDED_V1", [], signals=0, entries=0, denied=0, available=False)
    live["unavailable_reason"] = "Recorded live metrics contain no completed trade lifecycle for this date."
    v1 = _metrics("HILEGA_V1_REPLAY", [], signals=0, entries=0, denied=0)
    candidate = _metrics(STRATEGY_ID, [], signals=0, entries=0, denied=0)
    return {
        "session_date": session_date,
        "source": "WMA_GAP_FORWARD_CONFIRMATION",
        "source_id": f"wma-gap-forward:{session_date}",
        "evidence_level": "STRATEGY",
        "ce_available": False,
        "manifest": manifest,
        "audit_chain_ok": None,
        "audit_chain_issue": None,
        "reports": [],
        "report_count": 0,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "evidence_cohort": "NEW_FORWARD_CONFIRMATION",
        "performance_summary": [live, v1, candidate],
        "comparison": {"candidate_net_delta_vs_v1": 0.0, "losses_avoided": 0, "winners_denied": 0},
        "zero_trade_session": True,
        "observation_only": True,
        "execution_enabled": False,
        "warning": "Completed forward-confirmation session; canonical Hilega produced no completed trades.",
    }


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
    """Pair authoritative recorded entry/exit transitions without synthesizing.

    Directional live captures do not always repeat the lifecycle event in the
    projected transition list.  In that case the recorded owner transition is
    authoritative: NONE -> direction is an entry and direction -> NONE is an
    exit.  Explicit events remain the first-choice source.
    """
    active: dict[str, float] = {}
    values: list[float] = []
    seen: set[tuple[str, str, str]] = set()
    signals = 0
    def owner(value: Any) -> str | None:
        text = str(value or "").upper()
        if "BEARISH" in text:
            return "BEARISH"
        if "BULLISH" in text:
            return "BULLISH"
        return None

    def enter(direction: str, price: float | None) -> None:
        nonlocal signals
        if price is not None and direction not in active:
            active[direction] = price
            signals += 1

    def leave(direction: str, price: float | None) -> None:
        if price is not None and direction in active:
            entry = active.pop(direction)
            values.append(
                price - entry if direction == "BULLISH" else entry - price
            )

    for report in sorted(reports, key=lambda row: str(row.get("checkpoint") or "")):
        explicit_entry_or_exit = False
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
            if is_entry:
                explicit_entry_or_exit = True
                enter(direction, price)
            elif is_exit:
                explicit_entry_or_exit = True
                leave(direction, price)

        if explicit_entry_or_exit:
            continue

        strategy = report.get("strategy") or {}
        before = owner(strategy.get("state_before"))
        after = owner(strategy.get("state_after"))
        price = _number((report.get("bar") or {}).get("close"))

        # State transitions also preserve same-candle reversals. Close the old
        # owner before opening the new owner at the recorded candle close.
        if before != after:
            if before is not None:
                leave(before, price)
            if after is not None:
                enter(after, price)
    result = _metrics("LIVE_RECORDED_V1", values, signals=signals,
                      entries=signals, denied=0, available=bool(signals))
    if active:
        result["unresolved"] = len(active)
    if not signals:
        result["unavailable_reason"] = "No authoritative recorded live entry/exit lifecycle was available for this date."
    return result


def build_v1_session(session_date: str, root: Path | None = None) -> dict[str, Any]:
    """Present the canonical outcomes used as the WMA-gap control.

    This is intentionally sourced from the same frozen trade-results artifact as
    the candidate comparison.  It must never fall back to recorded live rows.
    """
    root, evidence_cohort = _root_for_session(session_date, root)
    trades = [row for row in _rows(root / RESULTS.name)
              if row.get("session_date") == session_date]
    if not trades:
        empty = _zero_trade_forward_session(session_date, root)
        if empty is not None:
            empty["strategy_id"] = "HILEGA_V1_REPLAY"
            empty["strategy_version"] = "canonical-v1"
            empty["source"] = "WMA_GAP_490_CANONICAL_CONTROL"
            return empty
        raise FileNotFoundError(session_date)
    reports: list[dict[str, Any]] = []
    values: list[float] = []
    for trade in trades:
        direction = str(trade.get("direction") or "")
        route = str(trade.get("route") or "CANONICAL")
        entry = _report(
            str(trade.get("entry_timestamp") or ""), trade,
            event="HILEGA_V1_CANONICAL_ENTRY", state_before="IDLE",
            state_after="ACTIVE", close=_number(trade.get("entry_price")),
            steps=[
                _step("Canonical directional signal", "PASS", direction,
                      "Canonical BULLISH or BEARISH signal",
                      "The frozen v1 control accepted this signal."),
                _step("Canonical route", "PASS", route,
                      "Opening, Route A or Route B",
                      "No WMA-gap delay or T+10 confirmation is applied."),
                _step("Entry timing", "PASS", trade.get("entry_timestamp"),
                      "Enter on the canonical signal",
                      "V1 enters immediately at its recorded control price."),
            ],
        )
        entry["strategy"].update({
            "strategy_id": "HILEGA_V1_REPLAY",
            "strategy_version": "canonical-v1",
            "directional_action": "HILEGA_V1_CANONICAL_ENTRY",
        })
        entry["transitions"][0]["source"] = "HILEGA_V1_REPLAY"
        entry["audit_integrity"]["source"] = "FROZEN_CANONICAL_CONTROL_ARTIFACT"
        reports.append(entry)

        value = _number(trade.get("canonical_points"))
        if value is not None:
            values.append(value)
        exit_row = _report(
            str(trade.get("exit_timestamp") or ""), trade,
            event="HILEGA_V1_CANONICAL_EXIT", state_before="ACTIVE",
            state_after="CLOSED", close=_number(trade.get("exit_price")),
            points=value, steps=[
                _step("Canonical exit", "PASS", trade.get("exit_timestamp"),
                      "Existing v1 exit lifecycle",
                      "The control exit is unchanged and contains no WMA-gap rule."),
                _step("NIFTY result", "PASS", value,
                      "Direction-normalized entry-to-exit points",
                      "Positive supports the trade direction; negative opposes it."),
            ],
        )
        exit_row["strategy"].update({
            "strategy_id": "HILEGA_V1_REPLAY",
            "strategy_version": "canonical-v1",
            "directional_action": "HILEGA_V1_CANONICAL_EXIT",
        })
        exit_row["transitions"][0]["source"] = "HILEGA_V1_REPLAY"
        exit_row["audit_integrity"]["source"] = "FROZEN_CANONICAL_CONTROL_ARTIFACT"
        reports.append(exit_row)

    reports.sort(key=lambda row: (
        str(row.get("checkpoint") or ""),
        str((row.get("audit_integrity") or {}).get("trade_id") or ""),
    ))
    control = _metrics("HILEGA_V1_REPLAY", values, signals=len(trades),
                       entries=len(trades), denied=0)
    candidate_session = build_wma_gap_session(session_date, root)
    return {
        **candidate_session,
        "source": "WMA_GAP_490_CANONICAL_CONTROL",
        "source_id": f"hilega-v1:{session_date}",
        "reports": reports,
        "report_count": len(reports),
        "strategy_id": "HILEGA_V1_REPLAY",
        "strategy_version": "canonical-v1",
        "evidence_cohort": evidence_cohort,
        "warning": (
            "Canonical Hilega v1 control reconstructed from the same frozen "
            "historical outcomes used by the WMA-gap comparison. Live rows are "
            "never substituted."
        ),
        "performance_summary": [
            candidate_session["performance_summary"][0],
            control,
            candidate_session["performance_summary"][2],
        ],
    }


def build_wma_gap_session(session_date: str, root: Path | None = None) -> dict[str, Any]:
    root, evidence_cohort = _root_for_session(session_date, root)
    trades = [row for row in _rows(root / RESULTS.name)
              if row.get("session_date") == session_date]
    if not trades:
        empty = _zero_trade_forward_session(session_date, root)
        if empty is not None:
            return empty
        raise FileNotFoundError(session_date)
    attempts_by_trade: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows(root / ATTEMPTS.name):
        if row.get("session_date") == session_date:
            attempts_by_trade[str(row.get("trade_id"))].append(row)
    timeline_by_trade: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows(root / TIMELINE.name):
        if row.get("session_date") == session_date:
            timeline_by_trade[str(row.get("trade_id"))].append(row)

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
        timeline = sorted(timeline_by_trade.get(trade_id, []),
                          key=lambda row: str(row.get("minute_timestamp") or ""))
        if timeline:
            reference = timeline[0]
            signal_report = reports[-1]
            signal_report["indicators"].update({
                "rsi9": _number(reference.get("reference_rsi9")),
                "ema3_rsi": _number(reference.get("reference_ema3_rsi")),
                "wma21_rsi": _number(reference.get("reference_wma21_rsi")),
            })
            signal_report["conditions"].update({
                "reference_5m_timestamp": reference.get("reference_5m_timestamp"),
                "evaluation_starts_at": reference.get("minute_timestamp"),
                "directional_wma_change": 0.0,
                "directional_gap": (
                    None if _number(reference.get("reference_ema3_rsi")) is None
                    or _number(reference.get("reference_wma21_rsi")) is None
                    else (
                        _number(reference.get("reference_ema3_rsi"))
                        - _number(reference.get("reference_wma21_rsi"))
                    ) * (1.0 if direction == "BULLISH" else -1.0)
                ),
            })
            signal_report["conditions"]["strategy_steps"] = [
                _step("Canonical Hilega signal", "PASS", direction,
                      "BULLISH or BEARISH canonical signal",
                      "This completed five-minute signal starts the observation window."),
                _step("Signal RSI9", "OBSERVED", reference.get("reference_rsi9"),
                      "Recorded at canonical signal", "Entry-time indicator evidence."),
                _step("Signal EMA3(RSI)", "OBSERVED", reference.get("reference_ema3_rsi"),
                      "Recorded at canonical signal", "Entry-time indicator evidence."),
                _step("Signal WMA21(RSI)", "OBSERVED", reference.get("reference_wma21_rsi"),
                      "Reference for directional change", "Every later minute is compared with this WMA21 value."),
                _step("First one-minute evaluation", "PENDING", reference.get("minute_timestamp"),
                      "After the signal candle completes", "No WMA-gap entry occurs on the signal row itself."),
            ]
        confirmed_at = str(trade.get("candidate_entry_timestamp") or "")
        last_window_stamp = next((
            str(row.get("minute_timestamp") or "")
            for row in reversed(timeline)
            if _bool(row.get("within_confirmation_window"))
        ), "")
        previous: dict[str, str] | None = None
        for minute in timeline:
            stamp = str(minute.get("minute_timestamp") or "")
            direction_sign = 1.0 if direction == "BULLISH" else -1.0
            strength = _number(minute.get("directional_wma_change"))
            ema = _number(minute.get("provisional_ema3_rsi"))
            wma = _number(minute.get("provisional_wma21_rsi"))
            gap = None if ema is None or wma is None else (ema - wma) * direction_sign
            previous_ema = _number((previous or {}).get("provisional_ema3_rsi"))
            previous_wma = _number((previous or {}).get("provisional_wma21_rsi"))
            previous_rsi = _number((previous or {}).get("provisional_rsi9"))
            previous_strength = _number((previous or {}).get("directional_wma_change"))
            previous_gap = (
                None if previous_ema is None or previous_wma is None
                else (previous_ema - previous_wma) * direction_sign
            )
            gap_delta = None if gap is None or previous_gap is None else gap - previous_gap
            ema_delta = None if ema is None or previous_ema is None else (ema - previous_ema) * direction_sign
            in_window = _bool(minute.get("within_confirmation_window"))
            armed = strength is not None and strength >= .75
            maintained = bool(previous) and armed and (_number(previous.get("directional_wma_change")) or -999) >= .75
            gap_positive = gap is not None and gap > 0
            gap_expanding = gap_delta is not None and gap_delta > 0
            ema_continuing = ema_delta is not None and ema_delta > 0
            aligned = _bool(minute.get("full_directional_alignment"))
            if confirmed_at and stamp == confirmed_at:
                event, before, after = "WMA_GAP_ENTRY", "WAITING_FOR_CONFIRMATION", "ACTIVE"
            elif confirmed_at and stamp > confirmed_at:
                event, before, after = "WMA_GAP_CONTINUATION", "ACTIVE", "ACTIVE"
            elif not confirmed_at and stamp == last_window_stamp:
                event, before, after = "WMA_GAP_NO_ENTRY_BY_T10", "WAITING_FOR_CONFIRMATION", "DENIED"
            elif not in_window:
                event, before, after = "WMA_GAP_POST_T10_OBSERVATION", "DENIED", "DENIED"
            else:
                event, before, after = "WMA_GAP_WAIT", "WAITING_FOR_CONFIRMATION", "WAITING_FOR_CONFIRMATION"
            steps = [
                _step("Canonical Hilega signal", "PASS", direction, "Canonical directional signal", "The existing strategy produced the setup."),
                _step("T+10 confirmation window", "PASS" if in_window else "CLOSED", minute.get("minutes_observed"), "Minutes 1 through 10", "New entries are forbidden after this window."),
                _step("Directional WMA21 strength", "PASS" if armed else "FAIL",
                      f"reference {minute.get('reference_wma21_rsi')} → current {wma}; directional change {strength}",
                      ">= 0.75", "Opposite or flat values continue waiting."),
                _step("Later one-minute persistence", "PASS" if maintained else "FAIL",
                      f"previous strength {previous_strength} → current strength {strength}",
                      "Previous and current minute >= 0.75", "The arm candle cannot confirm itself."),
                _step("Directional EMA3-WMA21 gap", "PASS" if gap_positive else "FAIL",
                      f"EMA3 {ema} · WMA21 {wma} · directional gap {gap}",
                      "> 0", "Bullish uses EMA-WMA; bearish uses WMA-EMA."),
                _step("EMA3-WMA21 gap expansion", "PASS" if gap_expanding else "FAIL",
                      f"previous gap {previous_gap} → current gap {gap} · delta {gap_delta}",
                      "> 0 vs prior minute", "Confirms that separation is increasing."),
                _step("EMA3 continuation", "PASS" if ema_continuing else "FAIL",
                      f"previous EMA3 {previous_ema} → current EMA3 {ema} · directional delta {ema_delta}",
                      "> 0 directionally", "EMA3 continuation is displayed as diagnostic evidence."),
                _step("RSI9 / EMA3 / WMA21 alignment", "PASS" if aligned else "FAIL",
                      f"RSI9 {minute.get('provisional_rsi9')} · EMA3 {ema} · WMA21 {wma}",
                      "Directionally aligned", "Alignment is displayed as diagnostic evidence."),
            ]
            if event == "WMA_GAP_NO_ENTRY_BY_T10":
                steps.append(_step(
                    "Confirmation deadline", "FAIL", "NO_ENTRY_BY_T10",
                    "All mandatory confirmation gates must pass by T+10",
                    "This is the final evaluated minute; failed values above explain the denial.",
                ))
            report = _report(stamp, trade, event=event, state_before=before,
                             state_after=after,
                             close=_number(minute.get("observed_close")), steps=steps)
            report["bar"] = {
                "open": _number(minute.get("observed_open")),
                "high": _number(minute.get("observed_high")),
                "low": _number(minute.get("observed_low")),
                "close": _number(minute.get("observed_close")),
                "volume": _number(minute.get("observed_volume")),
            }
            report["indicators"] = {
                "rsi9": _number(minute.get("provisional_rsi9")),
                "ema3_rsi": ema,
                "wma21_rsi": wma,
                "previous_rsi9": previous_rsi,
                "previous_ema3_rsi": previous_ema,
                "previous_wma21_rsi": previous_wma,
            }
            report["conditions"].update({
                "directional_wma_change": strength,
                "directional_gap": gap,
                "directional_gap_delta": gap_delta,
                "directional_ema_delta": ema_delta,
                "within_confirmation_window": in_window,
                "confirmation_tier": minute.get("confirmation_tier"),
                "points_from_original_entry": _number(minute.get("points_from_original_entry")),
            })
            reports.append(report)
            previous = minute

        if not timeline:
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
        elif not timeline:
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
        "evidence_cohort": evidence_cohort,
        "performance_summary": [live, v1, candidate],
        "comparison": {
            "candidate_net_delta_vs_v1": candidate["net_points"] - v1["net_points"],
            "losses_avoided": sum(1 for row in trades if row.get("candidate_decision") != "ENTRY" and (_number(row.get("canonical_points")) or 0) < 0),
            "winners_denied": sum(1 for row in trades if row.get("candidate_decision") != "ENTRY" and (_number(row.get("canonical_points")) or 0) > 0),
        },
        "observation_only": True, "execution_enabled": False,
        "warning": "Tested WMA-gap replay from immutable historical artifacts. Live strategy, orders and quantity are unchanged.",
    }
