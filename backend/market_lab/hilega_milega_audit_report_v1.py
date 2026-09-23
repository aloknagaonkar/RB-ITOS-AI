from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

MODEL = "HILEGA_MILEGA_CANONICAL_AUDIT_REPORT_V1"
STRATEGY_STAGES = {
    "INDICATOR_CALCULATION",
    "STRATEGY_DECISION",
    "STRATEGY_TRANSITION",
    "STRATEGY_DECISION_RESULT",
    "SESSION_CUTOFF_SOURCE",
}
OPTION_STAGES = {
    "OPTION_CANDIDATE_SET",
    "OPTION_CANDIDATE_MARKET_SNAPSHOT",
    "OPTION_SHADOW_LIFECYCLE_START",
    "OPTION_SHADOW_LIFECYCLE_RESTORE",
    "OPTION_SHADOW_LIFECYCLE_UPDATE",
    "OPTION_SHADOW_LIFECYCLE_EXIT",
    "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY",
    "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY",
    "OPTION_SHADOW_PENDING_EXIT_RESTORE",
}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _related_to_checkpoint(row: dict[str, Any], checkpoint: str) -> bool:
    if row.get("checkpoint") == checkpoint:
        return True
    p = row.get("payload") or {}
    if p.get("signal_bar") == checkpoint:
        return True
    if p.get("entry_time") == checkpoint:
        return True
    details = p.get("details") or {}
    if details.get("original_entry_time") == checkpoint:
        return True
    return False


def _transition_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("stage") != "STRATEGY_TRANSITION":
            continue
        p = row.get("payload") or {}
        out.append({
            "event_type": p.get("event_type") or row.get("status"),
            "event_time": p.get("event_time") or row.get("checkpoint"),
            "price": p.get("price"),
            "source": p.get("source"),
            "state_before": p.get("state_before"),
            "state_after": p.get("state_after"),
            "exit_reason": p.get("exit_reason"),
            "points": p.get("points"),
            "details": p.get("details"),
        })
    return out


def build_detailed_audit_report(
    rows: Iterable[dict[str, Any]],
    *,
    checkpoint: str,
    mode: str,
    chain_ok: bool | None = None,
    chain_issue: str | None = None,
) -> dict[str, Any]:
    all_rows = list(rows)
    related = [r for r in all_rows if _related_to_checkpoint(r, checkpoint)]
    # An exit checkpoint must display the entire corresponding CE trade, not
    # only records created at the exit candle. Strategy emits this immutable
    # original_entry_time in the structural/cutoff exit transition.
    linked_signal_bar = checkpoint
    for row in related:
        if row.get("stage") != "STRATEGY_TRANSITION":
            continue
        p = row.get("payload") or {}
        if row.get("checkpoint") != checkpoint:
            continue
        entry = (p.get("details") or {}).get("original_entry_time")
        if entry and ("EXIT" in str(p.get("event_type") or row.get("status") or "")):
            linked_signal_bar = entry
            break
    strategy_rows = [r for r in related if r.get("stage") in STRATEGY_STAGES]

    decision = next((r for r in strategy_rows if r.get("stage") == "STRATEGY_DECISION"), None)
    result = next((r for r in strategy_rows if r.get("stage") == "STRATEGY_DECISION_RESULT"), None)
    indicator = next((r for r in strategy_rows if r.get("stage") == "INDICATOR_CALCULATION"), None)
    dp = (decision or {}).get("payload") or {}
    rp = (result or {}).get("payload") or {}
    ip = (indicator or {}).get("payload") or {}

    option_rows = [r for r in all_rows if r.get("stage") in OPTION_STAGES and (
        _related_to_checkpoint(r, checkpoint) or
        (linked_signal_bar != checkpoint and _related_to_checkpoint(r, linked_signal_bar))
    )]
    candidate = next((r for r in option_rows if r.get("stage") == "OPTION_CANDIDATE_SET"), None)
    market_snapshot = next((r for r in option_rows if r.get("stage") == "OPTION_CANDIDATE_MARKET_SNAPSHOT"), None)
    lifecycle_start = next((r for r in option_rows if r.get("stage") in {"OPTION_SHADOW_LIFECYCLE_START", "OPTION_SHADOW_LIFECYCLE_RESTORE", "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY"} and (r.get("payload") or {}).get("status") == "ACTIVE"), None)
    if lifecycle_start is None:
        lifecycle_start = next((r for r in option_rows if r.get("stage") in {"OPTION_SHADOW_LIFECYCLE_START", "OPTION_SHADOW_LIFECYCLE_RESTORE", "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY"}), None)
    lifecycle_updates = [r for r in option_rows if r.get("stage") == "OPTION_SHADOW_LIFECYCLE_UPDATE"]
    lifecycle_exit = next((r for r in reversed(option_rows) if r.get("stage") in {"OPTION_SHADOW_LIFECYCLE_EXIT", "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY"}), None)

    conditions = {
        "rsi_cross_ema_up": dp.get("rsi_cross_ema_up"),
        "rsi_cross_wma_down": dp.get("rsi_cross_wma_down"),
        "rsi_gt_50": dp.get("rsi_gt_50"),
        "rsi_gt_wma": dp.get("rsi_gt_wma"),
        "ema_gt_wma": dp.get("ema_gt_wma"),
        "rsi_rising": dp.get("rsi_rising"),
        "ema_rising": dp.get("ema_rising"),
        "full_alignment": dp.get("full_alignment"),
    }

    return {
        "model": MODEL,
        "mode": mode,
        "checkpoint": checkpoint,
        "linked_signal_bar": linked_signal_bar,
        "strategy": {
            "strategy_id": dp.get("strategy_id") or rp.get("strategy_id") or ip.get("strategy_id"),
            "strategy_version": dp.get("strategy_version") or rp.get("strategy_version") or ip.get("strategy_version"),
            "state_before": dp.get("state_before"),
            "state_after": rp.get("state_after"),
            "selected_route": rp.get("selected_route"),
            "route_b_suppressed_by_route_a_priority": rp.get("route_b_suppressed_by_route_a_priority"),
            "events_emitted": rp.get("events_emitted") or [],
            "note": rp.get("note"),
        },
        "bar": {
            "open": dp.get("bar_open"),
            "high": dp.get("bar_high"),
            "low": dp.get("bar_low"),
            "close": dp.get("bar_close"),
            "volume": dp.get("bar_volume"),
        },
        "indicators": {
            "rsi9": dp.get("rsi9", ip.get("rsi9")),
            "ema3_rsi": dp.get("ema3_rsi", ip.get("ema3_rsi")),
            "wma21_rsi": dp.get("wma21_rsi", ip.get("wma21_rsi")),
            "previous_rsi9": dp.get("previous_rsi9"),
            "previous_ema3_rsi": dp.get("previous_ema3_rsi"),
            "previous_wma21_rsi": dp.get("previous_wma21_rsi"),
        },
        "conditions": conditions,
        "route_a": {
            "eligible": rp.get("route_a_eligible"),
            "pass": rp.get("route_a_pass"),
            "fail_reasons": rp.get("route_a_fail_reasons") or [],
        },
        "route_b": {
            "eligible": rp.get("route_b_eligible"),
            "pass": rp.get("route_b_pass"),
            "fail_reasons": rp.get("route_b_fail_reasons") or [],
        },
        "transitions": _transition_summary(strategy_rows),
        "option_candidate": None if candidate is None else {
            "status": candidate.get("status"),
            **(candidate.get("payload") or {}),
        },
        "option_market_snapshot": None if market_snapshot is None else {
            "status": market_snapshot.get("status"),
            **(market_snapshot.get("payload") or {}),
        },
        "option_lifecycle": {
            "start": None if lifecycle_start is None else {"status": lifecycle_start.get("status"), **(lifecycle_start.get("payload") or {})},
            "updates": [{"status": r.get("status"), **(r.get("payload") or {})} for r in lifecycle_updates],
            "exit": None if lifecycle_exit is None else {"status": lifecycle_exit.get("status"), **(lifecycle_exit.get("payload") or {})},
            "entry_retries": [{"status": r.get("status"), **(r.get("payload") or {})} for r in option_rows if r.get("stage") == "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY"],
            "exit_retries": [{"status": r.get("status"), **(r.get("payload") or {})} for r in option_rows if r.get("stage") == "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY"],
        },
        "audit_integrity": {
            "chain_ok": chain_ok,
            "chain_issue": chain_issue,
            "records": [
                {
                    "sequence": r.get("sequence"),
                    "stage": r.get("stage"),
                    "status": r.get("status"),
                    "checkpoint": r.get("checkpoint"),
                    "event_time": r.get("event_time"),
                    "previous_hash": r.get("previous_hash"),
                    "record_hash": r.get("record_hash"),
                }
                for r in related
            ],
        },
        "safety": {
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
        },
    }


def build_audit_index(rows: Iterable[dict[str, Any]], *, mode: str, chain_ok: bool | None = None, chain_issue: str | None = None) -> list[dict[str, Any]]:
    all_rows = list(rows)
    checkpoints = []
    seen = set()
    for r in all_rows:
        cp = r.get("checkpoint")
        if cp and cp not in seen and r.get("stage") == "STRATEGY_DECISION":
            seen.add(cp)
            checkpoints.append(cp)
    return [build_detailed_audit_report(all_rows, checkpoint=cp, mode=mode, chain_ok=chain_ok, chain_issue=chain_issue) for cp in checkpoints]
