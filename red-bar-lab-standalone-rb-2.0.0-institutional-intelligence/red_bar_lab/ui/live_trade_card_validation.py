from __future__ import annotations

from time import perf_counter
from typing import Any, Mapping


def _available(value: object) -> bool:
    return value not in (None, "", "—", "NOT_AVAILABLE")


def build_live_validation(card: Mapping[str, object], *, render_ms: float | None = None) -> dict[str, object]:
    """Build a read-only live-session validation summary for one selected trade."""
    status = str(card.get("status") or "OPEN").upper()
    freshness = str((card.get("freshness") or {}).get("status") or "UNAVAILABLE").upper()
    comparison = "EXIT" if status == "CLOSED" else "CURRENT"

    checks: list[dict[str, str]] = []

    def add(name: str, state: str, detail: str) -> None:
        checks.append({"check": name, "state": state, "detail": detail})

    add(
        "Telemetry freshness",
        "PASS" if freshness == "FRESH" else "WARN",
        freshness,
    )
    add(
        "Entry lifecycle",
        "PASS" if _available(card.get("entry_snapshot_source")) else "WARN",
        str(card.get("entry_snapshot_source") or "NOT_AVAILABLE"),
    )

    if status == "CLOSED":
        exit_source = str(card.get("exit_snapshot_source") or "NOT_AVAILABLE")
        exit_quality = str(card.get("exit_data_quality") or "NOT_AVAILABLE")
        add(
            "Exit lifecycle",
            "PASS" if exit_source != "NOT_AVAILABLE" else "WARN",
            f"{exit_source} · {exit_quality}",
        )

    add(
        f"{comparison} PCR and Delta",
        "PASS" if _available(card.get("current_pcr")) and _available(card.get("current_delta")) else "WARN",
        "Available" if _available(card.get("current_pcr")) and _available(card.get("current_delta")) else "Incomplete",
    )
    add(
        f"{comparison} option VWAP",
        "PASS" if _available(card.get("current_option_vwap")) else "WARMING_UP",
        "Available" if _available(card.get("current_option_vwap")) else "Waiting for usable persisted volume history",
    )
    add(
        f"{comparison} option RSI-14",
        "PASS" if _available(card.get("current_option_rsi14")) else "WARMING_UP",
        "Available" if _available(card.get("current_option_rsi14")) else "Requires at least 15 persisted option-price observations",
    )

    if render_ms is not None:
        state = "PASS" if render_ms <= 250.0 else "WARN" if render_ms <= 750.0 else "SLOW"
        add("Selected card render", state, f"{render_ms:.1f} ms")

    failing = [row for row in checks if row["state"] in {"WARN", "SLOW"}]
    warming = [row for row in checks if row["state"] == "WARMING_UP"]
    overall = "PASS" if not failing and not warming else "WARMING_UP" if not failing else "ATTENTION"
    return {
        "overall": overall,
        "checks": tuple(checks),
        "authority": "OBSERVATIONAL ONLY",
    }


def install(full_trade_card_module: Any) -> None:
    """Append live-session validation diagnostics to the selected Full Card."""
    if getattr(full_trade_card_module, "_live_validation_installed", False):
        return

    original_render = full_trade_card_module.render_active_trade_card

    def render_active_trade_card(st: Any, card: Mapping[str, object]) -> None:
        started = perf_counter()
        original_render(st, card)
        render_ms = (perf_counter() - started) * 1000.0
        validation = build_live_validation(card, render_ms=render_ms)
        st.markdown("#### Live Session Validation")
        st.caption(
            "Read-only UI validation for freshness, lifecycle completeness, indicator readiness, and selected-card render time."
        )
        st.metric("Validation Status", validation["overall"])
        st.dataframe(list(validation["checks"]), width="stretch", hide_index=True)
        st.caption("Operational State: NO STRATEGY ACTION — OBSERVATIONAL ONLY")

    full_trade_card_module.render_active_trade_card = render_active_trade_card
    full_trade_card_module._live_validation_installed = True


__all__ = ["build_live_validation", "install"]
