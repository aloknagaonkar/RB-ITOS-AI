from __future__ import annotations

"""
Branch C V2.4 — Same-candle RSI/WMA + EMA/WMA crossover validation.

Purpose:
- Explicitly allow RSI↑WMA21 and EMA3↑WMA21 on the same 5m candle.
- Do not require EMA3↑WMA21 on a later candle.
- Preserve the sequence requirement that RSI↑EMA3 arms the setup first.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicatorPoint:
    rsi: float
    ema3: float
    wma21: float


@dataclass(frozen=True)
class TransitionResult:
    rsi_up_ema: bool
    rsi_up_wma: bool
    ema_up_wma: bool
    active_setup: bool
    bullish: bool
    strong_bullish: bool


def cross_up(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a <= prev_b and a > b


def evaluate_transition(
    prev: IndicatorPoint,
    curr: IndicatorPoint,
    *,
    armed: bool,
) -> TransitionResult:
    """
    Evaluate a single 5-minute transition.

    Important:
    If the setup is already armed and RSI↑WMA occurs on this candle,
    ACTIVE_SETUP becomes true immediately. On that same candle:
      - RSI > 50 can make it BULLISH
      - EMA3 > WMA21 can make it STRONG_BULLISH

    Therefore a same-candle RSI↑WMA + EMA3↑WMA transition is valid.
    """
    rsi_up_ema = cross_up(prev.rsi, prev.ema3, curr.rsi, curr.ema3)
    rsi_up_wma = cross_up(prev.rsi, prev.wma21, curr.rsi, curr.wma21)
    ema_up_wma = cross_up(prev.ema3, prev.wma21, curr.ema3, curr.wma21)

    active_setup = armed and rsi_up_wma
    bullish = active_setup and curr.rsi > curr.wma21 and curr.rsi > 50.0

    # Deliberately use the state relation EMA3 > WMA21, not a requirement
    # that EMA↑WMA must happen on a later candle.
    strong_bullish = bullish and curr.ema3 > curr.wma21

    return TransitionResult(
        rsi_up_ema=rsi_up_ema,
        rsi_up_wma=rsi_up_wma,
        ema_up_wma=ema_up_wma,
        active_setup=active_setup,
        bullish=bullish,
        strong_bullish=strong_bullish,
    )


def main() -> int:
    # Screenshot-like example:
    # previous: RSI and EMA3 are below WMA21
    # current : both have crossed above WMA21
    prev = IndicatorPoint(rsi=48.0, ema3=46.0, wma21=50.0)
    curr = IndicatorPoint(rsi=56.0, ema3=52.0, wma21=51.0)

    result = evaluate_transition(prev, curr, armed=True)

    print("=== SAME-CANDLE CROSS VALIDATION V2.4 ===")
    print(f"previous: RSI={prev.rsi:.2f} EMA3={prev.ema3:.2f} WMA21={prev.wma21:.2f}")
    print(f"current : RSI={curr.rsi:.2f} EMA3={curr.ema3:.2f} WMA21={curr.wma21:.2f}")
    print()
    print(f"RSI_UP_WMA       = {result.rsi_up_wma}")
    print(f"EMA3_UP_WMA      = {result.ema_up_wma}")
    print(f"ACTIVE_SETUP     = {result.active_setup}")
    print(f"BULLISH          = {result.bullish}")
    print(f"STRONG_BULLISH   = {result.strong_bullish}")

    if not (
        result.rsi_up_wma
        and result.ema_up_wma
        and result.active_setup
        and result.bullish
        and result.strong_bullish
    ):
        raise SystemExit("FAIL: same-candle crossover was not promoted correctly")

    print("\nPASS: same-candle RSI↑WMA + EMA3↑WMA is accepted immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
