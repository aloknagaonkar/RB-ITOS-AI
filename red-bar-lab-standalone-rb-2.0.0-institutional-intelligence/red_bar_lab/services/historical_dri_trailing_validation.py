from __future__ import annotations

from dataclasses import dataclass, asdict
import pandas as pd


@dataclass(frozen=True)
class TrailingStopConfig:
    initial_stop_pct: float = 10.0
    activation_pct: float = 8.0
    trail_distance_pct: float = 5.0
    profit_lock_pct: float = 2.0


@dataclass(frozen=True)
class TrailingStopResult:
    entry_price: float
    exit_price: float
    return_pct: float
    exit_reason: str
    activated: bool
    activation_price: float
    peak_price: float
    highest_trailing_stop: float
    protected_points: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def simulate_trailing_stop(
    candles: pd.DataFrame,
    *,
    entry_moment,
    entry_price: float,
    baseline_exit_price: float | None = None,
    config: TrailingStopConfig | None = None,
) -> TrailingStopResult:
    cfg = config or TrailingStopConfig()
    entry = float(entry_price)
    frame = candles.copy()
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        exit_price = float(baseline_exit_price or entry)
        return TrailingStopResult(
            entry, exit_price, ((exit_price-entry)/entry)*100.0,
            "NO_FUTURE_CANDLES", False,
            entry*(1+cfg.activation_pct/100.0), entry,
            entry*(1-cfg.initial_stop_pct/100.0),
            exit_price-float(baseline_exit_price or exit_price),
        )

    ts = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    moment = pd.Timestamp(entry_moment)
    if moment.tzinfo is None:
        moment = moment.tz_localize("Asia/Kolkata")
    moment_utc = moment.tz_convert("UTC")
    frame = frame.loc[ts > moment_utc].copy()
    for column in ("high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["high", "low", "close"])

    initial_stop = entry * (1.0 - cfg.initial_stop_pct / 100.0)
    activation_price = entry * (1.0 + cfg.activation_pct / 100.0)
    profit_lock = entry * (1.0 + cfg.profit_lock_pct / 100.0)
    peak = entry
    trailing_stop = initial_stop
    highest_stop = initial_stop
    activated = False
    exit_price = float(
        baseline_exit_price
        if baseline_exit_price is not None
        else (float(frame.iloc[-1]["close"]) if not frame.empty else entry)
    )
    reason = "BASELINE_EXIT_FALLBACK" if baseline_exit_price is not None else "END_OF_DATA"

    for _, candle in frame.iterrows():
        high = float(candle["high"])
        low = float(candle["low"])
        peak = max(peak, high)
        if not activated and peak >= activation_price:
            activated = True
        if activated:
            trailing_stop = max(
                profit_lock,
                peak * (1.0 - cfg.trail_distance_pct / 100.0),
                trailing_stop,
            )
            highest_stop = max(highest_stop, trailing_stop)
            if low <= trailing_stop:
                exit_price = trailing_stop
                reason = "TRAILING_STOP"
                break
        elif low <= initial_stop:
            exit_price = initial_stop
            reason = "INITIAL_STOP"
            break

    return_pct = ((exit_price - entry) / entry) * 100.0 if entry else 0.0
    baseline = float(baseline_exit_price or exit_price)
    return TrailingStopResult(
        entry_price=entry,
        exit_price=exit_price,
        return_pct=return_pct,
        exit_reason=reason,
        activated=activated,
        activation_price=activation_price,
        peak_price=peak,
        highest_trailing_stop=highest_stop,
        protected_points=exit_price - baseline,
    )
