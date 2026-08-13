from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class ExitHealth:
    action: str
    health_score: float
    hard_exit_reason: str | None
    effective_stop: float | None
    initial_stop: float | None
    breakeven_price: float | None
    breakeven_armed: bool
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
    informational-only; trend continuation/exit is controlled by the completed
    underlying 5-minute candle relative to EMA10. OI/PCR/Greeks remain shadow.
    """

    def __init__(
        self,
        *,
        breakeven_trigger_pct: float = 15.0,
        trailing_trigger_pct: float = 20.0,
        trailing_distance_pct: float = 10.0,
    ):
        self.breakeven_trigger_pct = float(breakeven_trigger_pct)
        self.trailing_trigger_pct = float(trailing_trigger_pct)
        self.trailing_distance_pct = float(trailing_distance_pct)

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
    ) -> ExitHealth:
        entry = _num(position.get("entry_price"))
        current = _num(position.get("current_price"), entry)
        initial_stop = _num(
            position.get("initial_stop_price"),
            _num(position.get("stop_price")),
        )
        configured_stop = _num(position.get("stop_price"), initial_stop)
        # Kept for backward-compatible display/history only. TARGET_1 has no
        # operational exit authority after the EMA10 trend-exit change.
        target1 = _num(position.get("target1_price"))
        target2 = _num(position.get("target2_price"))

        mfe_points = max(0.0, _num(position.get("mfe_points")))
        peak_price = max(entry, current, entry + mfe_points)
        pnl_pct = (
            (current - entry) / entry * 100.0 if entry > 0 else 0.0
        )
        peak_pct = (
            (peak_price - entry) / entry * 100.0 if entry > 0 else 0.0
        )

        breakeven_armed = peak_pct >= self.breakeven_trigger_pct
        breakeven_price = entry if breakeven_armed else None

        trailing_active = peak_pct >= self.trailing_trigger_pct
        trailing_stop = None
        if trailing_active:
            trailing_stop = peak_price * (
                1.0 - self.trailing_distance_pct / 100.0
            )

        candidates = [
            value for value in (
                configured_stop if configured_stop > 0 else None,
                breakeven_price,
                trailing_stop,
            )
            if value is not None and value > 0
        ]
        effective_stop = max(candidates) if candidates else None

        reasons: list[str] = []
        hard_exit_reason = None

        # NIFTY thesis validation from original confirmed signal candle.
        nifty_thesis = "UNKNOWN"
        direction = str((signal or {}).get("direction") or "").upper()
        if signal and current_underlying is not None:
            confirmation_high = _num(signal.get("confirmation_high"))
            confirmation_low = _num(signal.get("confirmation_low"))
            if direction == "BEARISH" and confirmation_high > 0:
                if current_underlying > confirmation_high:
                    nifty_thesis = "INVALID"
                else:
                    nifty_thesis = "VALID"
            elif direction == "BULLISH" and confirmation_low > 0:
                if current_underlying < confirmation_low:
                    nifty_thesis = "INVALID"
                else:
                    nifty_thesis = "VALID"

        # Change 5: completed underlying 5-minute EMA10 owns trend exit.
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

        # Option technical health.
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
                rv = _num(rel_volume)
                volume_health = "HEALTHY" if rv >= 1.0 else "WEAK"

        # Shadow-only observations.
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

        # Operational hierarchy. Fixed TARGET_1 is intentionally absent.
        if effective_stop is not None and current <= effective_stop:
            if trailing_active and trailing_stop is not None and effective_stop == max(candidates):
                hard_exit_reason = "TRAILING_STOP"
            elif breakeven_armed and breakeven_price is not None and effective_stop >= breakeven_price:
                hard_exit_reason = "BREAKEVEN_STOP"
            else:
                hard_exit_reason = "HARD_STOP"
        elif eod_due:
            hard_exit_reason = "EOD_EXIT"
        elif ema10_exit_reason:
            hard_exit_reason = ema10_exit_reason
        elif nifty_thesis == "INVALID":
            hard_exit_reason = "NIFTY_INVALIDATION"
        elif opposite_red_bar_confirmed:
            hard_exit_reason = "OPPOSITE_RED_BAR"
        elif technical_failures >= 2:
            hard_exit_reason = "OPTION_TECHNICAL_BREAKDOWN"

        # Operational health score. Shadow OI/PCR/Greeks are intentionally
        # excluded so advisory evidence can never trigger EXIT/TIGHTEN.
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
            reasons.append("Trailing protection active.")
        elif breakeven_armed:
            action = "HOLD / PROTECT"
            reasons.append("Breakeven protection armed.")
        elif health < 50:
            action = "EXIT"
            reasons.append("Trade health below 50.")
        elif health < 70:
            action = "TIGHTEN"
            reasons.append("Trade health weakening.")
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
        next_trigger = " or ".join(trigger_parts) if trigger_parts else "Monitor EMA10 / health"

        return ExitHealth(
            action=action,
            health_score=round(health, 1),
            hard_exit_reason=hard_exit_reason,
            effective_stop=round(effective_stop, 2) if effective_stop is not None else None,
            initial_stop=round(initial_stop, 2) if initial_stop > 0 else None,
            breakeven_price=round(breakeven_price, 2) if breakeven_price is not None else None,
            breakeven_armed=breakeven_armed,
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
            underlying_5m_close=(round(underlying_5m_close, 2) if underlying_5m_close is not None else None),
            underlying_ema10=(round(underlying_ema10, 2) if underlying_ema10 is not None else None),
            ema10_trend=ema10_trend,
        )
