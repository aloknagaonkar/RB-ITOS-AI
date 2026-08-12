from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from red_bar_lab.context.service import RedBarMarketContextService
from red_bar_lab.context.volume_structure_service import (
    RedBarVolumeStructureService,
)
from red_bar_lab.features.store import RedBarFeatureStore

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class SignalPipelineState:
    signal_id: str
    market_context: bool
    volume_structure: bool
    options_context: bool
    core_eligible: bool
    hybrid_eligible: bool


@dataclass(frozen=True)
class PipelineRunReport:
    trading_date: str
    confirmed_signals: int
    market_built: int
    volume_built: int
    options_linked: int
    core_eligible: int
    hybrid_eligible: int
    errors: tuple[str, ...]


class RedBarIntelligencePipelineOrchestrator:
    """Coordinates independent collectors without coupling trading logic.

    Each enrichment stage is fault-isolated. Missing options never prevents
    price/volume context, and missing intelligence never blocks Red Bar
    signal/trade processing.
    """

    def __init__(
        self,
        *,
        historical,
        database,
        settings,
        options_collector=None,
    ):
        self.historical = historical
        self.database = database
        self.settings = settings
        self.options_collector = options_collector
        self.feature_store = RedBarFeatureStore(database)

    def _confirmed_signals(
        self,
        instrument_key: str,
        trading_date: str,
    ):
        return [
            row
            for row in self.database.read_signal_attempts(
                instrument_key,
                trading_date,
            )
            if row.get("signal_id") and row.get("confirmation_timestamp")
        ]

    def sync_day(
        self,
        *,
        instrument_key: str,
        trading_date: str,
        link_window_seconds: int = 120,
    ) -> PipelineRunReport:
        confirmed = self._confirmed_signals(
            instrument_key,
            trading_date,
        )
        errors = []
        market_built = 0
        volume_built = 0
        options_linked = 0

        if confirmed:
            existing_market = {
                str(row.get("signal_id"))
                for row in self.database.read_market_context_snapshots(
                    instrument_key,
                    trading_date,
                    trading_date,
                )
                if row.get("signal_id")
            }
            existing_volume = {
                str(row.get("signal_id"))
                for row in self.database.read_volume_structure_snapshots(
                    instrument_key,
                    trading_date,
                    trading_date,
                )
                if row.get("signal_id")
            }
            confirmed_ids = {
                str(row["signal_id"]) for row in confirmed
            }

            if confirmed_ids - existing_market:
                try:
                    service = RedBarMarketContextService(
                        self.historical,
                        self.database,
                        self.settings,
                    )
                    _, report = service.build_for_range(
                        instrument_key,
                        date.fromisoformat(trading_date),
                        date.fromisoformat(trading_date),
                    )
                    market_built = report.snapshots_built
                except Exception as exc:
                    errors.append(f"market_context: {exc}")

            if confirmed_ids - existing_volume:
                try:
                    service = RedBarVolumeStructureService(
                        self.historical,
                        self.database,
                        self.settings,
                    )
                    _, report = service.build_for_range(
                        instrument_key,
                        date.fromisoformat(trading_date),
                        date.fromisoformat(trading_date),
                    )
                    volume_built = report.snapshots_built
                except Exception as exc:
                    errors.append(f"volume_structure: {exc}")

            if self.options_collector is not None:
                try:
                    options_linked = (
                        self.options_collector
                        .link_nearest_pre_entry_snapshots(
                            instrument_key=instrument_key,
                            trading_date=trading_date,
                            max_age_seconds=link_window_seconds,
                        )
                    )
                except Exception as exc:
                    errors.append(f"options_link: {exc}")

        states = self.evaluate_day(
            instrument_key=instrument_key,
            trading_date=trading_date,
        )
        for state in states:
            self.database.upsert_signal_pipeline_status(
                {
                    "signal_id": state.signal_id,
                    "instrument_key": instrument_key,
                    "trading_date": trading_date,
                    "market_context_ready": int(state.market_context),
                    "volume_structure_ready": int(state.volume_structure),
                    "options_context_ready": int(state.options_context),
                    "core_eligible": int(state.core_eligible),
                    "hybrid_eligible": int(state.hybrid_eligible),
                    "last_error": None,
                }
            )

        if errors:
            self.database.update_pipeline_run_status(
                instrument_key=instrument_key,
                trading_date=trading_date,
                status="PARTIAL",
                message=" | ".join(errors)[:1000],
            )
        else:
            self.database.update_pipeline_run_status(
                instrument_key=instrument_key,
                trading_date=trading_date,
                status="HEALTHY",
                message=(
                    f"{len(states)} confirmed; "
                    f"{sum(s.core_eligible for s in states)} core eligible; "
                    f"{sum(s.hybrid_eligible for s in states)} hybrid eligible."
                ),
            )

        return PipelineRunReport(
            trading_date=trading_date,
            confirmed_signals=len(confirmed),
            market_built=market_built,
            volume_built=volume_built,
            options_linked=options_linked,
            core_eligible=sum(s.core_eligible for s in states),
            hybrid_eligible=sum(s.hybrid_eligible for s in states),
            errors=tuple(errors),
        )

    def evaluate_day(
        self,
        *,
        instrument_key: str,
        trading_date: str,
    ) -> list[SignalPipelineState]:
        confirmed = self._confirmed_signals(
            instrument_key,
            trading_date,
        )
        states = []
        for signal in confirmed:
            signal_id = str(signal["signal_id"])
            features = self.feature_store.get_features(signal_id)
            market = bool(features["market_context"])
            volume = bool(features["volume_structure"])
            options = bool(
                features["flat"].get("options_entry_aligned")
            )
            core = market and volume
            hybrid = core and options
            states.append(
                SignalPipelineState(
                    signal_id=signal_id,
                    market_context=market,
                    volume_structure=volume,
                    options_context=options,
                    core_eligible=core,
                    hybrid_eligible=hybrid,
                )
            )
        return states

    def validate_eod(
        self,
        *,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object]:
        states = self.evaluate_day(
            instrument_key=instrument_key,
            trading_date=trading_date,
        )
        confirmed = len(states)
        core = sum(s.core_eligible for s in states)
        hybrid = sum(s.hybrid_eligible for s in states)

        result = {
            "instrument_key": instrument_key,
            "trading_date": trading_date,
            "confirmed_signals": confirmed,
            "core_eligible": core,
            "hybrid_eligible": hybrid,
            "core_completeness_pct": (
                core / confirmed * 100.0 if confirmed else 100.0
            ),
            "hybrid_completeness_pct": (
                hybrid / confirmed * 100.0 if confirmed else 100.0
            ),
            "status": (
                "COMPLETE"
                if confirmed == 0 or core == confirmed
                else "INCOMPLETE"
            ),
        }
        self.database.upsert_eod_pipeline_validation(result)
        return result
