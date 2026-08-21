from red_bar_lab.ui.operations_readiness_wrapper import (
    build_live_operations_readiness_view,
)


class IncompleteMarketDatabase:
    path = None

    def read_signal_attempts(self, instrument_key, trading_date):
        return [{
            "signal_id": "RBV2-1",
            "confirmation_timestamp": "2026-08-21T10:20:00+05:30",
        }]

    def read_reference_levels(self, instrument_key, trading_date):
        return [{
            "level_type": "NEXT_RED_CANDLE",
            "timestamp": "2026-08-21T10:15:00+05:30",
            "high": 25010.0,
            "low": 24980.0,
            "midpoint": 24995.0,
            "data_quality": "VALID",
        }]

    def read_market_context_snapshots(self, instrument_key, start, end):
        return [{
            "signal_id": "RBV2-1",
            "instrument_key": instrument_key,
            "trading_date": start,
            "entry_timestamp": "2026-08-21T10:20:00+05:30",
            "session_open": 25000.0,
            "minutes_from_open": 65.0,
            "price_from_open_points": 20.0,
            "session_high_so_far": 25040.0,
            "session_low_so_far": 24980.0,
            "session_range_so_far": 60.0,
            "session_range_position": 0.66,
            "trend_5m": None,
        }]

    def read_volume_structure_snapshots(self, instrument_key, start, end):
        return [{
            "signal_id": "RBV2-1",
            "instrument_key": instrument_key,
            "trading_date": start,
            "entry_timestamp": "2026-08-21T10:20:00+05:30",
            "volume_current_1m": 1000.0,
            "volume_avg_20m": 800.0,
            "volume_trend_5m": "RISING",
            "price_volume_state": "BULLISH_ACCUMULATION",
            "structure_state": "EXPANSION",
        }]

    def read_option_context_snapshots(self, instrument_key, start, end):
        return [{
            "signal_id": "RBV2-1",
            "instrument_key": instrument_key,
            "trading_date": start,
            "entry_timestamp": "2026-08-21T10:20:00+05:30",
            "option_expiry": "2026-08-27",
            "option_snapshot_timestamp": "2026-08-21T10:20:30+05:30",
            "option_snapshot_delay_seconds": 30.0,
            "entry_aligned": 1,
            "option_spot_price": 25020.0,
            "atm_strike": 25000.0,
            "total_call_oi": 100000.0,
            "total_put_oi": 110000.0,
            "pcr_oi": 1.1,
        }]

    def read_option_context_by_signal(self, signal_id):
        return None


def test_missing_market_mandatory_field_blocks_market_core_and_hybrid():
    view = build_live_operations_readiness_view(
        IncompleteMarketDatabase(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        persist_outcomes=False,
    )

    assert view["stages"]["market"]["ready_count"] == 0
    assert view["stages"]["volume"]["ready_count"] == 1
    assert view["stages"]["options"]["ready_count"] == 1
    assert view["stages"]["core"]["ready_count"] == 0
    assert view["stages"]["hybrid"]["ready_count"] == 0

    row = view["drilldown"][0]
    assert row["Market"] == "MISSING"
    assert row["Market mandatory"] == "11/12 (91.7%)"
    assert row["Market missing mandatory"] == "trend_5m"
    assert "MARKET_MANDATORY_FIELDS_MISSING" in row["All reasons"]
