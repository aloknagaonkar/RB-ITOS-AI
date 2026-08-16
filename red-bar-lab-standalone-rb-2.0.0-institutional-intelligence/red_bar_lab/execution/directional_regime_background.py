from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.stateful_multitimeframe_regime import StatefulMultiTimeframeRegimeEngine
from red_bar_lab.intelligence.transition_sequence_state_machine import TransitionSequenceStateMachine
from red_bar_lab.intelligence.fresh_setup_signal_engine import FreshSetupSignalEngine
from red_bar_lab.services.stateful_regime_store import StatefulRegimeStore
from red_bar_lab.services.transition_sequence_store import TransitionSequenceStore
from red_bar_lab.services.attribution_context import build_attribution_context
from red_bar_lab.services.fresh_setup_signal_store import FreshSetupSignalStore
from red_bar_lab.services.fresh_setup_bundle import build_setup_bundles
from red_bar_lab.services.fresh_setup_bundle_store import FreshSetupBundleStore
from red_bar_lab.services.signal_trade_attribution import create_ledger_record
from red_bar_lab.services.signal_trade_attribution_store import SignalTradeAttributionStore
from red_bar_lab.execution.early_directional_entry import (
    EarlyOneMinuteDirectionalEntryEngine,
    append_bundle_once,
)
from red_bar_lab.execution.rsi_extreme_reversal import (
    RsiExtremeReversalEngine,
    append_rsi_signals_once,
)

IST = "Asia/Kolkata"


@dataclass(frozen=True)
class DirectionalBackgroundRefreshResult:
    status: str
    reason: str
    instrument_key: str | None = None
    regime: str | None = None
    transition_id: str | None = None
    signals_generated: int = 0
    bundles_generated: int = 0
    latest_bundle_id: str | None = None
    rsi_signals_generated: int = 0
    latest_rsi_signal_id: str | None = None

    def as_record(self) -> dict[str, object]:
        return dict(self.__dict__)


def _safe_instrument(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(value)
    )
    return safe.strip("_") or "UNKNOWN"


def _normalize_one_minute(frames: list[pd.DataFrame], now: pd.Timestamp) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True)
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()

    output = frame.copy()
    output["timestamp"] = pd.to_datetime(
        output["timestamp"], errors="coerce", utc=True
    ).dt.tz_convert(IST)
    for column in ("open", "high", "low", "close", "volume"):
        if column not in output.columns:
            output[column] = 0.0
        output[column] = pd.to_numeric(output[column], errors="coerce")

    output = (
        output.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
    )
    output = output[output["timestamp"] < now.floor("min")]
    return output.reset_index(drop=True)


def _completed_five_minute(one_minute: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    if one_minute.empty:
        return pd.DataFrame()
    bars = (
        one_minute.set_index("timestamp")
        .resample(
            "5min",
            origin="start_day",
            offset="15min",
            label="left",
            closed="left",
        )
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            source_rows=("close", "count"),
        )
        .dropna(subset=["open", "high", "low", "close"])
    )
    bars = bars[(bars["source_rows"] >= 5) & (bars.index < now.floor("5min"))]
    return bars.reset_index()


class DirectionalRegimeBackgroundCycle:
    def __init__(
        self,
        *,
        adapter,
        runs_root: str | Path,
        now_provider=None,
        lookback_days: int = 7,
    ):
        self.adapter = adapter
        self.runs_root = Path(runs_root)
        self.now_provider = now_provider
        self.lookback_days = max(2, int(lookback_days))

    def _now(self) -> pd.Timestamp:
        raw = self.now_provider() if self.now_provider else pd.Timestamp.now(tz=IST)
        value = pd.Timestamp(raw)
        if value.tzinfo is None:
            return value.tz_localize(IST)
        return value.tz_convert(IST)

    def _load_frames(self, provider, instrument_key: str, now: pd.Timestamp) -> list[pd.DataFrame]:
        frames: list[pd.DataFrame] = []
        today = now.date()
        try:
            history = provider.historical_candles(
                instrument_key,
                today - timedelta(days=self.lookback_days),
                today - timedelta(days=1),
                interval_minutes=1,
            )
            if history is not None and not history.empty:
                frames.append(history)
        except Exception:
            pass
        try:
            intraday = provider.intraday_candles(
                instrument_key,
                interval_minutes=1,
            )
            if intraday is not None and not intraday.empty:
                frames.append(intraday)
        except Exception:
            pass
        return frames

    def run(self) -> DirectionalBackgroundRefreshResult:
        provider = getattr(self.adapter, "provider", None)
        instrument_key = getattr(self.adapter, "underlying_key", None)
        if provider is None or not instrument_key:
            return DirectionalBackgroundRefreshResult(
                status="UNAVAILABLE",
                reason="UNDERLYING_CANDLE_PROVIDER_UNAVAILABLE",
                instrument_key=instrument_key,
            )
        now = self._now()
        frames = self._load_frames(provider, str(instrument_key), now)
        one = _normalize_one_minute(frames, now)
        safe = _safe_instrument(str(instrument_key))
        normalized_key = str(instrument_key).upper().replace("_", " ")
        is_nifty_50 = normalized_key in {
            "NSE INDEX|NIFTY 50",
            "NSE:NIFTY 50",
            "NIFTY 50",
        }
        rsi_signals = (
            [
                signal.as_record()
                for signal in RsiExtremeReversalEngine().detect(
                    one,
                    instrument_key=str(instrument_key),
                )
            ]
            if is_nifty_50
            else []
        )
        rsi_path = (
            self.runs_root
            / "rsi_extreme_reversal_v1"
            / f"{safe}.jsonl"
        )
        rsi_signals_generated = (
            append_rsi_signals_once(rsi_path, rsi_signals)
            if is_nifty_50
            else 0
        )
        fresh_rsi_signals = [
            row
            for row in rsi_signals
            if pd.Timestamp(row["detected_at"]) <= now
            <= pd.Timestamp(row["fresh_until"])
        ]
        latest_rsi = fresh_rsi_signals[-1] if fresh_rsi_signals else None

        five = _completed_five_minute(one, now)
        if len(one) < 35 or len(five) < 35:
            return DirectionalBackgroundRefreshResult(
                status="READY" if latest_rsi is not None else "UNAVAILABLE",
                reason=(
                    "RSI_READY_DRI_UNAVAILABLE"
                    if latest_rsi is not None
                    else f"INSUFFICIENT_COMPLETED_CANDLES:1M={len(one)};5M={len(five)}"
                ),
                instrument_key=str(instrument_key),
                signals_generated=(1 if latest_rsi is not None else 0),
                rsi_signals_generated=rsi_signals_generated,
                latest_rsi_signal_id=(
                    str(latest_rsi.get("signal_id") or "")
                    if latest_rsi is not None
                    else None
                ),
            )

        regime_store = StatefulRegimeStore(
            self.runs_root / "stateful_regime_v43" / f"{safe}.jsonl"
        )
        transition_store = TransitionSequenceStore(
            self.runs_root / "transition_sequence_v43" / f"{safe}.jsonl"
        )
        signal_store = FreshSetupSignalStore(
            self.runs_root / "fresh_setup_signals_v43" / f"{safe}.jsonl"
        )
        bundle_store = FreshSetupBundleStore(
            self.runs_root / "fresh_setup_bundles_v43" / f"{safe}.jsonl"
        )
        ledger_store = SignalTradeAttributionStore(
            self.runs_root / "signal_trade_attribution_v43" / f"{safe}.jsonl"
        )

        snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
            one, five, previous_state=regime_store.latest()
        ).as_record()
        snapshot["instrument_key"] = str(instrument_key)
        snapshot["source"] = "PAPER_TRADING_BACKGROUND_CYCLE"
        regime_store.append_once(snapshot)

        early = EarlyOneMinuteDirectionalEntryEngine().evaluate(
            one,
            five_minute_regime=str(
                snapshot.get("five_minute_regime") or "SIDEWAYS"
            ),
            instrument_key=str(instrument_key),
        )
        early_bundle = (
            early.bundle if early.status == "READY" else None
        )
        if early_bundle is not None:
            append_bundle_once(
                self.runs_root
                / "fresh_setup_bundles_v43"
                / f"{safe}.jsonl",
                early_bundle,
            )

        transition = TransitionSequenceStateMachine().advance(
            snapshot, previous=transition_store.latest()
        )
        if transition is None:
            return DirectionalBackgroundRefreshResult(
                status=(
                    "READY"
                    if early_bundle is not None or latest_rsi is not None
                    else "NO_SIGNAL"
                ),
                reason=(
                    "EARLY_1M_DIRECTIONAL_BUNDLE_READY"
                    if early_bundle is not None
                    else "RSI_EXTREME_REVERSAL_SIGNAL_READY"
                    if latest_rsi is not None
                    else "NO_ACTIVE_DIRECTIONAL_TRANSITION"
                ),
                instrument_key=str(instrument_key),
                regime=str(snapshot.get("current_regime") or ""),
                signals_generated=(
                    1 if early_bundle is not None else 0
                ),
                bundles_generated=(
                    1 if early_bundle is not None else 0
                ),
                latest_bundle_id=(
                    str(early_bundle.get("bundle_id") or "")
                    if early_bundle is not None
                    else None
                ),
                rsi_signals_generated=rsi_signals_generated,
                latest_rsi_signal_id=(
                    str(latest_rsi.get("signal_id") or "")
                    if latest_rsi is not None
                    else None
                ),
            )

        transition_record = transition.as_record()
        transition_record["source"] = "PAPER_TRADING_BACKGROUND_CYCLE"
        transition_store.append_once(transition_record)

        attribution = build_attribution_context(snapshot, transition_record).as_record()
        generated = [
            signal.as_record()
            for signal in FreshSetupSignalEngine().detect(
                snapshot, transition_record, attribution
            )
        ]
        setup_records, _ = signal_store.resolve_many_once(generated)
        bundles = [bundle.as_record() for bundle in build_setup_bundles(setup_records)]

        for bundle in bundles:
            bundle["current_regime"] = snapshot.get("current_regime")
            bundle["bullish_score"] = snapshot.get("bullish_score")
            bundle["bearish_score"] = snapshot.get("bearish_score")
            bundle["source"] = "PAPER_TRADING_BACKGROUND_CYCLE"

        bundle_store.append_many_once(bundles)

        for bundle in bundles:
            bundle_id = str(bundle.get("bundle_id") or "")
            if bundle_id and ledger_store.by_bundle(bundle_id) is None:
                ledger_store.upsert(
                    create_ledger_record(
                        bundle,
                        instrument_key=str(instrument_key),
                    ).as_record()
                )

        latest_bundle = bundles[-1] if bundles else None
        return DirectionalBackgroundRefreshResult(
            status="READY" if bundles or latest_rsi is not None else "NO_SIGNAL",
            reason=(
                "FRESH_SETUP_BUNDLE_READY"
                if bundles
                else "RSI_EXTREME_REVERSAL_SIGNAL_READY"
                if latest_rsi is not None
                else "NO_FRESH_SETUP_FROM_CURRENT_SNAPSHOT"
            ),
            instrument_key=str(instrument_key),
            regime=str(snapshot.get("current_regime") or ""),
            transition_id=str(transition_record.get("transition_id") or ""),
            signals_generated=len(setup_records),
            bundles_generated=len(bundles),
            latest_bundle_id=(
                str(latest_bundle.get("bundle_id") or "")
                if latest_bundle
                else None
            ),
            rsi_signals_generated=rsi_signals_generated,
            latest_rsi_signal_id=(
                str(latest_rsi.get("signal_id") or "")
                if latest_rsi is not None
                else None
            ),
        )
