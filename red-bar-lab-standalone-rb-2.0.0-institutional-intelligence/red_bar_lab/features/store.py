from __future__ import annotations

from dataclasses import dataclass


MARKET_FIELDS = (
    "session_open",
    "previous_close",
    "previous_high",
    "previous_low",
    "gap_points",
    "gap_pct",
    "minutes_from_open",
    "price_from_open_points",
    "price_from_open_pct",
    "session_high_so_far",
    "session_low_so_far",
    "session_range_so_far",
    "session_range_position",
    "distance_to_previous_high",
    "distance_to_previous_low",
    "opening_range_15_high",
    "opening_range_15_low",
    "opening_range_15_position",
    "atr14_5m",
    "ema9_5m",
    "ema21_5m",
    "trend_5m",
    "realized_volatility_30m_pct",
)

VOLUME_STRUCTURE_FIELDS = (
    "volume_current_1m",
    "volume_avg_20m",
    "relative_volume_20m",
    "volume_trend_5m",
    "price_volume_state",
    "compression_ratio_20m",
    "structure_state",
    "breakout_strength",
    "range_width_20m",
    "higher_high_count_20m",
    "lower_low_count_20m",
    "bullish_structure_score",
    "bearish_structure_score",
)

OPTIONS_FIELDS = (
    "option_expiry",
    "option_snapshot_timestamp",
    "option_snapshot_delay_seconds",
    "option_spot_price",
    "atm_strike",
    "total_call_oi",
    "total_put_oi",
    "pcr_oi",
    "total_call_oi_change",
    "total_put_oi_change",
    "pcr_oi_change",
    "call_wall_strike",
    "put_wall_strike",
    "max_pain_strike",
    "atm_call_iv",
    "atm_put_iv",
    "atm_call_delta",
    "atm_put_delta",
    "atm_call_gamma",
    "atm_put_gamma",
    "atm_call_theta",
    "atm_put_theta",
    "atm_call_vega",
    "atm_put_vega",
)


@dataclass(frozen=True)
class FeatureStoreHealth:
    confirmed_signals: int
    market_context: int
    volume_structure: int
    options_context: int
    complete_core_context: int
    complete_with_options: int


class RedBarFeatureStore:
    """Single read interface for entry-time features.

    Options features are exposed to the intelligence dataset only when the
    snapshot is explicitly marked entry-aligned. This prevents a manually
    captured late option-chain snapshot from leaking future information.
    """

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _indexed(rows):
        return {
            str(row.get("signal_id")): row
            for row in rows
            if row.get("signal_id")
        }

    def get_features(self, signal_id: str) -> dict[str, object]:
        market = self.database.read_market_context_by_signal(signal_id)
        volume = self.database.read_volume_structure_by_signal(signal_id)
        options = self.database.read_option_context_by_signal(signal_id)

        nested = {
            "signal_id": signal_id,
            "market_context": market or {},
            "volume_structure": volume or {},
            "options_context": options or {},
        }
        nested["flat"] = self._flatten(market, volume, options)
        return nested

    @staticmethod
    def _flatten(market, volume, options):
        flat = {}

        market = market or {}
        volume = volume or {}
        options = options or {}

        for field in MARKET_FIELDS:
            flat[field] = market.get(field)

        for field in VOLUME_STRUCTURE_FIELDS:
            flat[field] = volume.get(field)

        # Only entry-aligned option data can become a prediction feature.
        aligned = bool(options.get("entry_aligned"))
        for field in OPTIONS_FIELDS:
            flat[field] = options.get(field) if aligned else None

        flat["options_entry_aligned"] = 1 if aligned else 0
        return flat

    def rows_for_range(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        market = self._indexed(
            self.database.read_market_context_snapshots(
                instrument_key, date_from, date_to
            )
        )
        volume = self._indexed(
            self.database.read_volume_structure_snapshots(
                instrument_key, date_from, date_to
            )
        )
        options = self._indexed(
            self.database.read_option_context_snapshots(
                instrument_key, date_from, date_to
            )
        )

        signal_ids = set(market) | set(volume) | set(options)
        rows = []

        for signal_id in sorted(signal_ids):
            merged = {"signal_id": signal_id}
            merged.update(
                self._flatten(
                    market.get(signal_id),
                    volume.get(signal_id),
                    options.get(signal_id),
                )
            )
            rows.append(merged)

        return rows

    def health(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> FeatureStoreHealth:
        signals = self.database.read_signal_attempts_range(
            instrument_key, date_from, date_to
        )
        confirmed = {
            str(row.get("signal_id"))
            for row in signals
            if row.get("signal_id")
            and row.get("confirmation_timestamp")
        }

        market = {
            str(row.get("signal_id"))
            for row in self.database.read_market_context_snapshots(
                instrument_key, date_from, date_to
            )
            if row.get("signal_id")
        }
        volume = {
            str(row.get("signal_id"))
            for row in self.database.read_volume_structure_snapshots(
                instrument_key, date_from, date_to
            )
            if row.get("signal_id")
        }
        options = {
            str(row.get("signal_id"))
            for row in self.database.read_option_context_snapshots(
                instrument_key, date_from, date_to
            )
            if row.get("signal_id") and bool(row.get("entry_aligned"))
        }

        core = confirmed & market & volume
        all_context = core & options

        return FeatureStoreHealth(
            confirmed_signals=len(confirmed),
            market_context=len(confirmed & market),
            volume_structure=len(confirmed & volume),
            options_context=len(confirmed & options),
            complete_core_context=len(core),
            complete_with_options=len(all_context),
        )
