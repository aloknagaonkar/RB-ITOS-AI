from __future__ import annotations

from typing import Any


RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"


def _fmt_number(value: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        if value is None or value == "":
            return "Not available"
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "Not available"


def _strategy_label(source: object) -> str:
    if str(source or "") == RSI_STRATEGY_SOURCE:
        return "RSI Extreme Reversal"
    return str(source or "Standard execution")


def build_strategy_attribution(
    order: dict[str, object],
    checkpoint: dict[str, object] | None,
    telemetry: dict[str, object] | None,
) -> dict[str, object]:
    source = str(order.get("execution_strategy_source") or "")
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
        telemetry_status = str(
            telemetry.get("support_classification") or "NOT_AVAILABLE"
        )
        telemetry_authority = str(
            telemetry.get("authority") or "OBSERVATIONAL_ONLY"
        )
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

    return {
        "order_id": order.get("order_id"),
        "contract": order.get("tradingsymbol"),
        "strategy": _strategy_label(source),
        "strategy_source": source or "STANDARD",
        "exit_policy": f"{stop_pct} stop · {target_text}",
        "exit_mode": str(order.get("exit_mode") or "STANDARD"),
        "checkpoint_status": checkpoint_status,
        "checkpoint_detail": checkpoint_detail,
        "telemetry_status": telemetry_status,
        "telemetry_authority": telemetry_authority,
        "telemetry_detail": telemetry_detail,
        "merge_status": str(order.get("merge_status") or "Not recorded"),
        "rsi_signal_id": str(order.get("rsi_signal_id") or ""),
        "rsi_confirmation_timestamp": str(
            order.get("rsi_confirmation_timestamp") or ""
        ),
    }
