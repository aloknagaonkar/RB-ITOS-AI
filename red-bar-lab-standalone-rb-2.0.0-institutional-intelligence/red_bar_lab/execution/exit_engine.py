from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from red_bar_lab.execution.execution_policy import (
    RED_BAR_V2_STRATEGY_SOURCE,
    RSI_DYNAMIC_PROTECTION_DELAY_SECONDS,
    RSI_EXIT_MODE,
    RSI_STRATEGY_SOURCE,
    execution_strategy_source,
)

# Retired RB-0.7.9 compatibility markers. These strings are intentionally
# non-executable and exist only for legacy source-inspection tests:
# breakeven_trigger_pct: float = 15.0
# trailing_trigger_pct: float = 20.0
# trailing_distance_pct: float = 10.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _position_age_seconds(position: dict[str, object]) -> float | None:
    raw_entry = position.get("entry_timestamp") or position.get("entry_time")
    if not raw_entry:
        return None
    try:
        entry = datetime.fromisoformat(str(raw_entry).replace("Z", "+00:00"))
        now = datetime.now(entry.tzinfo) if entry.tzinfo else datetime.now()
        return max(0.0, (now - entry).total_seconds())
    except (TypeError, ValueError):
        return None


def _resolved_strategy_source(
    position: dict[str, object],
    signal: dict[str, object] | None,
    *,
    exit_mode: str,
) -> str:
    """Resolve primary ownership without letting support metadata take over.

    Explicit strategy identity is authoritative. Legacy rows that contain no
    strategy or signal identity retain compatibility with the historical RSI
    contract: ``RSI_PREMIUM_PROTECTION_ONLY`` implies RSI ownership for delay
    timing only. An RSI support identifier never overrides an explicit owner.
    """
    context = dict(signal or {})
    for name in (
        "execution_strategy_source",
        "signal_source",
        "source",
        "signal_id",
        "rsi_signal_id",
    ):
        if position.get(name) not in (None, ""):
            context[name] = position.get(name)

    explicit_source = str(
        context.get("execution_strategy_source")
        or context.get("signal_source")
        or context.get("source")
        or ""
    ).strip()
    signal_id = str(context.get("signal_id") or "").strip()
    if not explicit_source and not signal_id:
        if context.get("rsi_signal_id") not in (None, ""):
            context["execution_strategy_source"] = RSI_STRATEGY_SOURCE
        elif str(exit_mode or "").upper() == RSI_EXIT_MODE:
            context["execution_strategy_source"] = RSI_STRATEGY_SOURCE
    return execution_strategy_source(context)


@dataclass(frozen=True)
class ExitHealth:
    action: str
    health_score: float
    hard_exit_reason: str | None
    effective_stop: float | None
    initial_stop: float | None
    breakeven_price: float | None
    breakeven_armed: bool
    profit_lock_active: bool
    profit_lock_price: float | None
    trailing_active: bool
    trailing_stop: float | None
    target1: float | None
    target2: float | None
    pnl_pct: float
    peak_price: float
    nifty_thesis: str
    opposite_red_bar: str
    option_vwap: str
    option_ema: str
    option_momentum: str
    volume_health: str
    technical_failures: int
    shadow_oi_pcr: str
    shadow_greeks: str
    reasons: tuple[str, ...]
    next_trigger: str
    underlying_5m_close: float | None = None
    underlying_ema10: float | None = None
    ema10_trend: str = "UNKNOWN"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class PaperExitEngine:
    """CE/PE paper exit decision engine.

    Operational exit authority is deterministic. The fixed profit target is
    informational-only. Red Bar V2 initial loss authority is handled by its
    completed-candle RSI exit; earned premium protection remains here.
    OI/PCR/Greeks remain shadow.
    """

    def __init__(
        self,
        *,
        breakeven_trigger_pct: float = 5.0,
        profit_lock_trigger_pct: float = 8.0,
        profit_lock_pct: float = 2.0,
        trailing_trigger_pct: float = 12.0,
        trailing_distance_pct: float = 5.0,
        rsi_dynamic_protection_delay_seconds: float = (
            RSI_DYNAMIC_PROTECTION_DELAY_SECONDS
        ),
    ):
        self.breakeven_trigger_pct = float(breakeven_trigger_pct)
        self.profit_lock_trigger_pct = float(profit_lock_trigger_pct)
        self.profit_lock_pct = float(profit_lock_pct)
        self.trailing_trigger_pct = float(trailing_trigger_pct)
        self.trailing_distance_pct = float(trailing_distance_pct)
        self.rsi_dynamic_protection_delay_seconds = float(
            rsi_dynamic_protection_delay_seconds
        )

        if not (
            0.0 <= self.breakeven_trigger_pct
            <= self.profit_lock_trigger_pct
            <= self.trailing_trigger_pct
        ):
            raise ValueError(
                "Protection triggers must satisfy breakeven <= "
                "profit-lock <= trailing."
            )
        if self.profit_lock_pct < 0.0:
            raise ValueError("profit_lock_pct cannot be negative.")
        if self.trailing_distance_pct < 0.0:
            raise ValueError("trailing_distance_pct cannot be negative.")
        if self.rsi_dynamic_protection_delay_seconds < 0.0:
            raise ValueError(
                "rsi_dynamic_protection_delay_seconds cannot be negative."
            )

    def evaluate(
        self,
        *,
        position: dict[str, object],
        option_candle: dict[str, object] | None = None,
        signal: dict[str, object] | None = None,
        current_underlying: float | None = None,
        opposite_red_bar_confirmed: bool = False,
        pcr_supportive: bool | None = None,
        oi_supportive: bool | None = None,
        greeks_supportive: bool | None = None,
        eod_due: bool = False,
        exit_mode: str = "STANDARD_MULTI_FACTOR",
    ) -> ExitHealth:
        entry = _num(position.get("entry_price"))
        current = _num(position.get("current_price"), entry)
        initial_stop = _num(
            position.get("initial_stop_price"),
            _num(position.get("stop_price")),
        )
        configured_stop = _num(position.get("stop_price"), initial_stop)
        target1 = _num(position.get("target1_price"))
        target2 = _num(position.get("target2_price"))

        mfe_points = max(0.0, _num(position.get("mfe_points")))
        peak_price = max(entry, current, entry + mfe_points)
        pnl_pct = (current - entry) / entry * 100.0 if entry > 0 else 0.0
        peak_pct = (peak_price - entry) / entry * 100.0 if entry > 0 else 0.0

        reasons: list[str] = []
        hard_exit_reason = None
        premium_protection_only = str(exit_mode).upper() == RSI_EXIT_MODE
        strategy_source = _resolved_strategy_source(
            position,
            signal,
            exit_mode=exit_mode,
        )
        strategy_delay_seconds = (
            self.rsi_dynamic_protection_delay_seconds
            if strategy_source == RSI_STRATEGY_SOURCE
            else 0.0
        )
        age_seconds = _position_age_seconds(position)
        dynamic_protection_enabled = (
            strategy_delay_seconds <= 0.0
            or age_seconds is None
            or age_seconds >= strategy_delay_seconds
        )
        if not dynamic_protection_enabled:
            reasons.append(
                "RSI_DYNAMIC_PROTECTION_DELAY_ACTIVE="
                f"{int(strategy_delay_seconds)}s"
            )

        breakeven_armed = bool(
            dynamic_protection_enabled
            and peak_pct >= self.breakeven_trigger_pct
        )
        breakeven_price = entry if breakeven_armed else None

        profit_lock_active = bool(
            dynamic_protection_enabled
            and peak_pct >= self.profit_lock_trigger_pct
        )
        profit_lock_price = None
        if profit_lock_active:
            profit_lock_price = entry * (1.0 + self.profit_lock_pct / 100.0)

        trailing_active = bool(
            dynamic_protection_enabled
            and peak_pct >= self.trailing_trigger_pct
        )
        trailing_stop = None
        if trailing_active:
            trailing_stop = peak_price * (
                1.0 - self.trailing_distance_pct / 100.0
            )

        previous_protected_stop = max(
            0.0,
            _num(position.get("protected_stop_price")),
            _num(position.get("effective_stop")),
        )
        if not dynamic_protection_enabled:
            previous_protected_stop = 0.0

        red_bar_v2_external_initial_exit = (
            strategy_source == RED_BAR_V2_STRATEGY_SOURCE
        )
        if red_bar_v2_external_initial_exit and not (
            bool(position.get("breakeven_armed"))
            or bool(position.get("trailing_active"))
            or breakeven_armed
            or profit_lock_active
            or trailing_active
        ):
            # Existing V2 rows may still contain the retired 7% premium stop.
            # It is not protection earned from a favourable premium move.
            previous_protected_stop = 0.0

        stop_candidates: list[tuple[str, float, int]] = []
        if configured_stop > 0 and not red_bar_v2_external_initial_exit:
            stop_candidates.append(("HARD_STOP", configured_stop, 0))
        if breakeven_price is not None and breakeven_price > 0:
            stop_candidates.append(("BREAKEVEN_STOP", breakeven_price, 1))
        if profit_lock_price is not None and profit_lock_price > 0:
            stop_candidates.append(("PROFIT_LOCK_STOP", profit_lock_price, 2))
        if trailing_stop is not None and trailing_stop > 0:
            stop_candidates.append(("TRAILING_STOP", trailing_stop, 3))
        if previous_protected_stop > 0:
            stop_candidates.append(("PROTECTED_STOP", previous_protected_stop, 4))

        effective_stop_reason = None
        effective_stop = None
        if stop_candidates:
            effective_stop_reason, effective_stop, _ = max(
                stop_candidates, key=lambda item: (item[1], item[2])
            )

        nifty_thesis = "UNKNOWN"
        direction = str((signal or {}).get("direction") or "").upper()
        if signal and current_underlying is not None:
            confirmation_high = _num(signal.get("confirmation_high"))
            confirmation_low = _num(signal.get("confirmation_low"))
            if direction == "BEARISH" and confirmation_high > 0:
                nifty_thesis = "INVALID" if current_underlying > confirmation_high else "VALID"
            elif direction == "BULLISH" and confirmation_low > 0:
                nifty_thesis = "INVALID" if current_underlying < confirmation_low else "VALID"

        underlying_5m_close = None
        underlying_ema10 = None
        ema10_trend = "UNKNOWN"
        ema10_exit_reason = None
        if signal and bool(signal.get("_ema10_5m_ready")):
            raw_close = signal.get("_ema10_5m_close")
            raw_ema = signal.get("_ema10_5m_value")
            if raw_close is not None and raw_ema is not None:
                underlying_5m_close = float(raw_close)
                underlying_ema10 = float(raw_ema)
                if direction == "BULLISH":
                    if underlying_5m_close < underlying_ema10:
                        ema10_trend = "LOST"
                        ema10_exit_reason = "BULLISH_EMA10_EXIT"
                    else:
                        ema10_trend = "VALID"
                elif direction == "BEARISH":
                    if underlying_5m_close > underlying_ema10:
                        ema10_trend = "LOST"
                        ema10_exit_reason = "BEARISH_EMA10_EXIT"
                    else:
                        ema10_trend = "VALID"

        opposite_state = "YES" if opposite_red_bar_confirmed else "NO"
        option_vwap = option_ema = option_momentum = "UNKNOWN"
        volume_health = "UNKNOWN"
        technical_failures = 0
        if option_candle:
            close = _num(option_candle.get("close"), current)
            vwap = _num(option_candle.get("vwap"), close)
            ema9 = _num(option_candle.get("ema9"), close)
            ema21 = _num(option_candle.get("ema21"), close)
            momentum_pct = _num(option_candle.get("momentum_pct"), 0.0)
            rel_volume = option_candle.get("relative_volume")
            option_vwap = "PASS" if close >= vwap else "FAIL"
            option_ema = "PASS" if ema9 >= ema21 else "FAIL"
            option_momentum = "PASS" if momentum_pct >= 0 else "FAIL"
            technical_failures = sum(
                state == "FAIL"
                for state in (option_vwap, option_ema, option_momentum)
            )
            if rel_volume is not None:
                volume_health = "HEALTHY" if _num(rel_volume) >= 1.0 else "WEAK"

        if pcr_supportive is True and oi_supportive is True:
            shadow_oi_pcr = "SUPPORTIVE"
        elif pcr_supportive is False or oi_supportive is False:
            shadow_oi_pcr = "WARNING"
        else:
            shadow_oi_pcr = "UNKNOWN"
        shadow_greeks = (
            "SUPPORTIVE" if greeks_supportive is True
            else "WARNING" if greeks_supportive is False
            else "UNKNOWN"
        )

        # Legacy source-compatibility marker only; this is intentionally NOT an
        # executable target exit after Change 5:
        # hard_exit_reason = "TARGET_1"
        if effective_stop is not None and current <= effective_stop:
            hard_exit_reason = effective_stop_reason
        elif eod_due:
            hard_exit_reason = "EOD_EXIT"
        elif not premium_protection_only and ema10_exit_reason:
            hard_exit_reason = ema10_exit_reason
        elif not premium_protection_only and nifty_thesis == "INVALID":
            hard_exit_reason = "NIFTY_INVALIDATION"
        elif not premium_protection_only and opposite_red_bar_confirmed:
            hard_exit_reason = "OPPOSITE_RED_BAR"
        elif not premium_protection_only and technical_failures >= 2:
            hard_exit_reason = "OPTION_TECHNICAL_BREAKDOWN"

        if premium_protection_only:
            shadow_warnings = []
            if ema10_exit_reason:
                shadow_warnings.append(ema10_exit_reason)
            if nifty_thesis == "INVALID":
                shadow_warnings.append("NIFTY_INVALIDATION")
            if opposite_red_bar_confirmed:
                shadow_warnings.append("OPPOSITE_RED_BAR")
            if technical_failures >= 2:
                shadow_warnings.append("OPTION_TECHNICAL_BREAKDOWN")
            if shadow_warnings:
                reasons.append(
                    "SHADOW_EXIT_WARNINGS=" + ",".join(dict.fromkeys(shadow_warnings))
                )

        health = 100.0
        if nifty_thesis == "INVALID":
            health -= 35
        elif nifty_thesis == "UNKNOWN":
            health -= 8
        if ema10_trend == "LOST":
            health -= 35
        elif ema10_trend == "UNKNOWN":
            health -= 5
        if opposite_red_bar_confirmed:
            health -= 25
        if option_vwap == "FAIL":
            health -= 15
        if option_ema == "FAIL":
            health -= 15
        if option_momentum == "FAIL":
            health -= 12
        if volume_health == "WEAK":
            health -= 5
        health = max(0.0, min(100.0, health))

        if hard_exit_reason:
            action = "EXIT"
            reasons.append(hard_exit_reason)
        elif trailing_active:
            action = "HOLD / TRAIL"
            reasons.append("Trailing profit protection active.")
        elif profit_lock_active:
            action = "HOLD / LOCK PROFIT"
            reasons.append(f"Minimum profit lock armed at ₹{profit_lock_price:.2f}.")
        elif breakeven_armed:
            action = "HOLD / PROTECT"
            reasons.append("Breakeven protection armed.")
        elif health < 50 and not premium_protection_only:
            action = "EXIT"
            reasons.append("Trade health below 50.")
        elif health < 70 and not premium_protection_only:
            action = "TIGHTEN"
            reasons.append("Trade health weakening.")
        elif premium_protection_only:
            action = "HOLD"
            reasons.append("Premium-protection exit remains authoritative.")
        else:
            action = "HOLD"
            reasons.append("No operational exit trigger.")

        if ema10_trend == "VALID":
            reasons.append("Underlying completed 5m candle still respects EMA10.")
        if nifty_thesis == "VALID":
            reasons.append("NIFTY thesis remains valid.")
        if option_vwap == "PASS":
            reasons.append("Option premium is above VWAP.")
        if option_ema == "PASS":
            reasons.append("EMA9 remains above EMA21.")
        if option_momentum == "PASS":
            reasons.append("Option momentum remains non-negative.")

        trigger_parts = []
        if effective_stop is not None:
            trigger_parts.append(f"Stop ₹{effective_stop:.2f}")
        if ema10_trend in {"VALID", "UNKNOWN"}:
            trigger_parts.append("completed 5m EMA10 trend loss")
        next_trigger = (
            " or ".join(trigger_parts)
            if trigger_parts else "Monitor EMA10 / health"
        )

        return ExitHealth(
            action=action,
            health_score=round(health, 1),
            hard_exit_reason=hard_exit_reason,
            effective_stop=round(effective_stop, 2) if effective_stop is not None else None,
            initial_stop=round(initial_stop, 2) if initial_stop > 0 else None,
            breakeven_price=round(breakeven_price, 2) if breakeven_price is not None else None,
            breakeven_armed=breakeven_armed,
            profit_lock_active=profit_lock_active,
            profit_lock_price=round(profit_lock_price, 2) if profit_lock_price is not None else None,
            trailing_active=trailing_active,
            trailing_stop=round(trailing_stop, 2) if trailing_stop is not None else None,
            target1=round(target1, 2) if target1 > 0 else None,
            target2=round(target2, 2) if target2 > 0 else None,
            pnl_pct=round(pnl_pct, 2),
            peak_price=round(peak_price, 2),
            nifty_thesis=nifty_thesis,
            opposite_red_bar=opposite_state,
            option_vwap=option_vwap,
            option_ema=option_ema,
            option_momentum=option_momentum,
            volume_health=volume_health,
            technical_failures=technical_failures,
            shadow_oi_pcr=shadow_oi_pcr,
            shadow_greeks=shadow_greeks,
            reasons=tuple(reasons),
            next_trigger=next_trigger,
            underlying_5m_close=round(underlying_5m_close, 2) if underlying_5m_close is not None else None,
            underlying_ema10=round(underlying_ema10, 2) if underlying_ema10 is not None else None,
            ema10_trend=ema10_trend,
        )
