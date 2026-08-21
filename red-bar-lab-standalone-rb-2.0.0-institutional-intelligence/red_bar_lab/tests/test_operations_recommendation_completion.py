from red_bar_lab.ui.operations_readiness_wrapper import build_live_operations_readiness_view


class CompleteDatabase:
    path = None

    def read_signal_attempts(self, instrument_key, trading_date):
        return [
            {
                "signal_id": "RBV2-1",
                "confirmation_timestamp": "2026-08-20T10:20:00+05:30",
                "rsi_7": 31.0,
                "rsi_candle_count": 20,
                "rsi_timestamp": "2026-08-20T10:19:00+05:30",
            }
        ]

    def read_reference_levels(self, instrument_key, trading_date):
        return [
            {
                "level_type": "NEXT_RED_CANDLE",
                "timestamp": "2026-08-20T10:15:00+05:30",
                "high": 25010.0,
                "low": 24980.0,
                "midpoint": 24995.0,
                "data_quality": "VALID",
            }
        ]

    def read_market_context_snapshots(self, instrument_key, start, end):
        return [
            {
                "signal_id": "RBV2-1",
                "instrument_key": instrument_key,
                "trading_date": start,
                "entry_timestamp": "2026-08-20T10:20:00+05:30",
                "session_open": 25000.0,
                "minutes_from_open": 65,
                "price_from_open_points": 10.0,
                "session_high_so_far": 25030.0,
                "session_low_so_far": 24980.0,
                "session_range_so_far": 50.0,
                "session_range_position": 0.6,
                "trend_5m": "UPTREND",
            }
        ]

    def read_volume_structure_snapshots(self, instrument_key, start, end):
        return [
            {
                "signal_id": "RBV2-1",
                "instrument_key": instrument_key,
                "trading_date": start,
                "entry_timestamp": "2026-08-20T10:20:00+05:30",
                "volume_current_1m": 1000,
                "volume_avg_20m": 900,
                "volume_trend_5m": "RISING",
                "price_volume_state": "BULLISH_ACCUMULATION",
                "structure_state": "EXPANSION",
            }
        ]

    def read_option_context_snapshots(self, instrument_key, start, end):
        return [
            {
                "signal_id": "RBV2-1",
                "instrument_key": instrument_key,
                "trading_date": start,
                "entry_timestamp": "2026-08-20T10:20:00+05:30",
                "option_expiry": "2026-08-27",
                "option_snapshot_timestamp": "2026-08-20T10:20:30+05:30",
                "option_snapshot_delay_seconds": 30,
                "entry_aligned": 1,
                "option_spot_price": 25010,
                "atm_strike": 25000,
                "total_call_oi": 100000,
                "total_put_oi": 110000,
                "pcr_oi": 1.1,
            }
        ]

    def read_option_context_by_signal(self, signal_id):
        return None

    def read_latest_option_chain_snapshot(self, instrument_key, trading_date):
        return [
            {"strike": strike, "call_oi": 1000 + strike, "put_oi": 2000 + strike}
            for strike in range(24800, 25301, 50)
        ]


def test_completed_recommendations_are_exposed_in_live_view():
    view = build_live_operations_readiness_view(
        CompleteDatabase(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-20",
        persist_outcomes=False,
    )

    assert view["stages"]["core"]["ready_count"] == 1
    assert view["stages"]["hybrid"]["ready_count"] == 1
    assert view["rsi_readiness"]["status"] == "READY"
    assert view["option_chain_window"]["status"] == "READY"
    assert len(view["option_chain_window"]["selected_strikes"]) == 9
    assert len(view["evidence_bundles"]) == 1
    assert view["evidence_bundles"][0]["authority"] == "OBSERVATIONAL_ONLY"
    assert view["evidence_bundle_persistence"]["status"] == "SKIPPED"
