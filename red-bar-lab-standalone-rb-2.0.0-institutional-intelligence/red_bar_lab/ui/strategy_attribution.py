from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


RED_BAR_STRATEGY_SOURCE = "RED_BAR"
DIRECTIONAL_REGIME_STRATEGY_SOURCE = "DIRECTIONAL_REGIME"
RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"
UNKNOWN_STRATEGY_SOURCE = "UNATTRIBUTED_LEGACY"


_SOURCE_ALIASES = {
    "RED_BAR": RED_BAR_STRATEGY_SOURCE,
    "RED_BAR_V1": RED_BAR_STRATEGY_SOURCE,
    "RB": RED_BAR_STRATEGY_SOURCE,
    "STANDARD": RED_BAR_STRATEGY_SOURCE,
    "STANDARD_EXECUTION": RED_BAR_STRATEGY_SOURCE,
    "DIRECTIONAL_REGIME": DIRECTIONAL_REGIME_STRATEGY_SOURCE,
    "DIRECTIONAL_REGIME_V1": DIRECTIONAL_REGIME_STRATEGY_SOURCE,
    "DRI": DIRECTIONAL_REGIME_STRATEGY_SOURCE,
    "RSI_EXTREME_REVERSAL": RSI_STRATEGY_SOURCE,
    "RSI_EXTREME_REVERSAL_V1": RSI_STRATEGY_SOURCE,
    "RSI": RSI_STRATEGY_SOURCE,
}

_LABELS = {
    RED_BAR_STRATEGY_SOURCE: "Red Bar",
    DIRECTIONAL_REGIME_STRATEGY_SOURCE: "Directional Regime",
    RSI_STRATEGY_SOURCE: "RSI Extreme Reversal",
    UNKNOWN_STRATEGY_SOURCE: "Unattributed legacy trade",
}


def _fmt_number(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        if value is None or value == "":
            return "Not available"
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "Not available"


def _text(value: object, fallback: str = "Not recorded") -> str:
    text = str(value or "").strip()
    return text or fallback


def normalize_strategy_source(order: Mapping[str, object]) -> str:
    """Resolve the primary strategy without treating supporting filters as owners."""
    explicit = str(order.get("execution_strategy_source") or "").strip().upper()
    if explicit in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[explicit]

    signal_id = str(order.get("signal_id") or "").strip().upper()
    rsi_signal_id = str(order.get("rsi_signal_id") or "").strip().upper()
    if rsi_signal_id or signal_id.startswith("RSI-"):
        return RSI_STRATEGY_SOURCE
    if signal_id.startswith(("DRI-", "DIR-")):
        return DIRECTIONAL_REGIME_STRATEGY_SOURCE
    if signal_id.startswith("RB-"):
        return RED_BAR_STRATEGY_SOURCE

    signal_sources = order.get("signal_sources")
    if isinstance(signal_sources, Sequence) and not isinstance(signal_sources, (str, bytes)):
        normalized = {
            _SOURCE_ALIASES.get(str(item or "").strip().upper())
            for item in signal_sources
        }
        normalized.discard(None)
        if len(normalized) == 1:
            return next(iter(normalized))

    return UNKNOWN_STRATEGY_SOURCE


def strategy_label(source: object) -> str:
    normalized = _SOURCE_ALIASES.get(str(source or "").strip().upper(), str(source or ""))
    return _LABELS.get(normalized, str(normalized or "Unattributed legacy trade"))


def _supporting_intelligence(order: Mapping[str, object]) -> list[str]:
    support: list[str] = []
    reason = str(order.get("entry_reason") or "").upper()
    if "DIRECTIONAL_REGIME" in reason or order.get("directional_regime_status"):
        status = _text(order.get("directional_regime_status"), "ACTIVE")
        support.append(f"DRI {status}")
    if order.get("opportunity_score") not in (None, "") or "OPPORTUNITY" in reason:
        support.append("Opportunity Engine")
    if order.get("selection_score") not in (None, "") or "TSS=" in reason:
        support.append("Historical Performance Selection")
    if order.get("execution_probability_pct") not in (None, "") or "PROB=" in reason:
        support.append("Institutional Committee")
    if order.get("expected_value_pct") not in (None, "") or "EV=" in reason:
        support.append("Expected-Value Gate")
    if order.get("merge_status") not in (None, ""):
        support.append(f"Signal merge: {order.get('merge_status')}")
    return list(dict.fromkeys(support))


def _executor(order: Mapping[str, object]) -> str:
    reason = str(order.get("entry_reason") or "").upper()
    if "RB093_QUEUE_APPROVED" in reason:
        return "RB093_BACKGROUND_QUEUE_EXECUTOR"
    if "QUEUE_APPROVED" in reason:
        return "BACKGROUND_QUEUE_EXECUTOR"
    opened_by = str(order.get("opened_by") or order.get("execution_actor") or "").strip()
    return opened_by or "LEGACY_PAPER_AUTOMATION"


def build_strategy_attribution(
    order: dict[str, object],
    checkpoint: dict[str, object] | None,
    telemetry: dict[str, object] | None,
) -> dict[str, object]:
    source = normalize_strategy_source(order)
    horizon = int(order.get("evaluation_horizon_minutes") or 0)
    target_pct = order.get("strategy_target_pct")
    target_text = (
        "No fixed target"
        if target_pct in (None, "")
        else f"{_fmt_number(target_pct)}%"
    )
    stop_pct = _fmt_number(order.get("strategy_stop_loss_pct"), suffix="%")

    if checkpoint:
        checkpoint_status = "Captured"
        checkpoint_detail = (
            f"T+{checkpoint.get('horizon_minutes')} · "
            f"premium {_fmt_number(checkpoint.get('checkpoint_price'))} · "
            f"return {_fmt_number(checkpoint.get('return_pct'), suffix='%')} · "
            f"MFE {_fmt_number(checkpoint.get('mfe_points'))} · "
            f"MAE {_fmt_number(checkpoint.get('mae_points'))}"
        )
    elif horizon > 0:
        checkpoint_status = "Pending"
        checkpoint_detail = f"T+{horizon} checkpoint pending"
    else:
        checkpoint_status = "Not configured"
        checkpoint_detail = "No evaluation horizon configured"

    if telemetry:
        telemetry_status = str(telemetry.get("support_classification") or "NOT_AVAILABLE")
        telemetry_authority = str(telemetry.get("authority") or "OBSERVATIONAL_ONLY")
        telemetry_detail = (
            f"premium {_fmt_number(telemetry.get('premium_return_pct'), suffix='%')} · "
            f"OI Δ {_fmt_number(telemetry.get('oi_change'))} · "
            f"relative volume {_fmt_number(telemetry.get('relative_volume'))} · "
            f"spread {_fmt_number(telemetry.get('spread_pct'), suffix='%')} · "
            f"IV {_fmt_number(telemetry.get('iv'))}"
        )
    else:
        telemetry_status = "NOT_AVAILABLE"
        telemetry_authority = "OBSERVATIONAL_ONLY"
        telemetry_detail = "No option/OI observation stored yet"

    support = _supporting_intelligence(order)
    signal_id = _text(order.get("signal_id"))
    entry_role = _text(
        order.get("entry_role")
        or order.get("role")
        or order.get("rsi_entry_role"),
        "PRIMARY",
    )
    return {
        "order_id": order.get("order_id"),
        "contract": order.get("tradingsymbol"),
        "strategy": strategy_label(source),
        "strategy_source": source,
        "signal_id": signal_id,
        "bundle_id": _text(order.get("bundle_id")),
        "candidate_id": _text(order.get("candidate_id")),
        "entry_role": entry_role,
        "entry_mode": _text(order.get("entry_mode"), "STANDARD"),
        "queue_source": "RB093_QUEUE" if "RB093" in str(order.get("entry_reason") or "").upper() else "LEGACY_QUEUE",
        "opened_by": _executor(order),
        "supporting_intelligence": support,
        "supporting_intelligence_text": " + ".join(support) if support else "None recorded",
        "candidate_rank": order.get("candidate_rank"),
        "candidate_score": order.get("candidate_score"),
        "selection_score": order.get("selection_score"),
        "execution_probability_pct": order.get("execution_probability_pct"),
        "expected_value_pct": order.get("expected_value_pct"),
        "exit_policy_owner": strategy_label(source),
        "exit_policy": f"{stop_pct} stop · {target_text}",
        "exit_mode": str(order.get("exit_mode") or "STANDARD"),
        "checkpoint_status": checkpoint_status,
        "checkpoint_detail": checkpoint_detail,
        "telemetry_status": telemetry_status,
        "telemetry_authority": telemetry_authority,
        "telemetry_detail": telemetry_detail,
        "merge_status": str(order.get("merge_status") or "Not recorded"),
        "rsi_signal_id": str(order.get("rsi_signal_id") or ""),
        "rsi_confirmation_timestamp": str(order.get("rsi_confirmation_timestamp") or ""),
        "attribution_confidence": "EXPLICIT" if order.get("execution_strategy_source") else "INFERRED_FROM_SIGNAL" if source != UNKNOWN_STRATEGY_SOURCE else "UNATTRIBUTED",
        "source_read_only": True,
    }


def build_strategy_performance_summary(
    orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Build read-only open/closed/P&L counts by primary strategy."""
    buckets: dict[str, dict[str, object]] = {}
    for raw in orders:
        order = dict(raw)
        source = normalize_strategy_source(order)
        bucket = buckets.setdefault(source, {
            "strategy_source": source,
            "strategy": strategy_label(source),
            "open_trades": 0,
            "closed_trades": 0,
            "open_pnl": 0.0,
            "closed_pnl": 0.0,
            "total_trades": 0,
        })
        bucket["total_trades"] = int(bucket["total_trades"]) + 1
        status = str(order.get("status") or "").upper()
        if status == "OPEN":
            bucket["open_trades"] = int(bucket["open_trades"]) + 1
            bucket["open_pnl"] = float(bucket["open_pnl"]) + float(order.get("unrealized_pnl") or 0.0)
        elif status == "CLOSED":
            bucket["closed_trades"] = int(bucket["closed_trades"]) + 1
            bucket["closed_pnl"] = float(bucket["closed_pnl"]) + float(order.get("realized_pnl") or 0.0)
    rows = list(buckets.values())
    rows.sort(key=lambda row: (-int(row["total_trades"]), str(row["strategy"])))
    return rows


def attribution_counts(orders: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = Counter(normalize_strategy_source(dict(order)) for order in orders)
    return dict(counts)


__all__ = [
    "RED_BAR_STRATEGY_SOURCE",
    "DIRECTIONAL_REGIME_STRATEGY_SOURCE",
    "RSI_STRATEGY_SOURCE",
    "UNKNOWN_STRATEGY_SOURCE",
    "normalize_strategy_source",
    "strategy_label",
    "build_strategy_attribution",
    "build_strategy_performance_summary",
    "attribution_counts",
]
