from red_bar_lab.services.signal_enrichment_outcome_store import (
    read_signal_enrichment_outcomes,
)
from red_bar_lab.ui.operations_readiness_wrapper import (
    build_live_operations_readiness_view,
)


def _market(signal_id):
    return {
        "signal_id": signal_id,
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-21",
        "entry_timestamp": "2026-08-21T10:20:00+05:30",
        "session_open": 25000.0,
        "minutes_from_open": 65.0,
        "price_from_open_points": 20.0,
        "session_high_so_far": 25040.0,
        "session_low_so_far": 24980.0,
        "session_range_so_far": 60.0,
        "session_range_position": 0.66,
        "trend_5m": "UPTREND",
    }


def _volume(signal_id):
    return {
        "signal_id": signal_id,
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-21",
        "entry_timestamp": "2026-08-21T10:20:00+05:30",
        "volume_current_1m": 1000.0,
        "volume_avg_20m": 800.0,
        "volume_trend_5m": "RISING",
        "price_volume_state": "BULLISH_ACCUMULATION",
        "structure_state": "EXPANSION",
    }


def _option(signal_id):
    return {
        "signal_id": signal_id,
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-21",
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
    }


class FakeDatabase:
    def __init__(self, path=None):
        self.path = path

    def read_signal_attempts(self, instrument_key, trading_date):
        return [
            {
                "signal_id": "RBV2-1",
                "confirmation_timestamp": "2026-08-21T10:20:00+05:30",
            },
            {
                "signal_id": "RBV2-2",
                "confirmation_timestamp": "2026-08-21T10:25:00+05:30",
            },
            {
                "signal_id": "RB-LEGACY",
                "confirmation_timestamp": "2026-08-21T10:30:00+05:30",
            },
        ]

    def read_reference_levels(self, instrument_key, trading_date):
        return [
            {
                "level_type": "NEXT_RED_CANDLE",
                "timestamp": "2026-08-21T10:15:00+05:30",
                "high": 25010.0,
                "low": 24980.0,
                "midpoint": 24995.0,
                "data_quality": "VALID",
            }
        ]

    def read_market_context_snapshots(self, instrument_key, start, end):
        return [_market("RBV2-1"), _market("RBV2-2")]

    def read_volume_structure_snapshots(self, instrument_key, start, end):
        return [_volume("RBV2-1")]

    def read_option_context_snapshots(self, instrument_key, start, end):
        return [_option("RBV2-1"), _option("RBV2-2")]

    def read_option_context_by_signal(self, signal_id):
        return None


def test_live_view_uses_v2_scope_and_exact_signal_intersections():
    view = build_live_operations_readiness_view(
        FakeDatabase(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )
    assert view["readiness_scope"] == "RED_BAR_V2"
    assert view["confirmed_count"] == 2
    assert view["stages"]["reference"]["ready_count"] == 2
    assert view["stages"]["market"]["ready_count"] == 2
    assert view["stages"]["volume"]["ready_count"] == 1
    assert view["stages"]["options"]["ready_count"] == 2
    assert view["stages"]["core"]["ready_count"] == 1
    assert view["stages"]["hybrid"]["ready_count"] == 1


def test_live_view_exposes_missing_stage_reason_per_signal():
    view = build_live_operations_readiness_view(
        FakeDatabase(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )
    rows = {row["Signal"]: row for row in view["drilldown"]}
    assert rows["RBV2-1"]["CORE"] == "YES"
    assert rows["RBV2-1"]["HYBRID"] == "YES"
    assert rows["RBV2-2"]["CORE"] == "NO"
    assert rows["RBV2-2"]["HYBRID"] == "NO"
    assert "VOLUME_MANDATORY_FIELDS_MISSING" in rows["RBV2-2"]["All reasons"]


def test_live_view_keeps_execution_blocked_and_observational():
    view = build_live_operations_readiness_view(
        FakeDatabase(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )
    assert view["authority"] == "OBSERVATIONAL_ONLY"
    assert view["domains"]["execution"]["status"] == "BLOCKED"
    assert view["domains"]["execution"]["primary_reason"] == "EXECUTION_POLICY_NOT_APPROVED"


def test_live_view_persists_four_stage_outcomes_per_confirmed_signal(tmp_path):
    database_path = tmp_path / "operations.db"
    view = build_live_operations_readiness_view(
        FakeDatabase(database_path),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )
    assert view["outcome_persistence"]["status"] == "READY"
    assert view["outcome_persistence"]["persisted_count"] == 8
    rows = read_signal_enrichment_outcomes(database_path)
    assert len(rows) == 8
    volume = next(
        row
        for row in rows
        if row["signal_id"] == "RBV2-2" and row["stage"] == "VOLUME"
    )
    assert volume["status"] == "MISSING"
    assert volume["reason_code"] == "VOLUME_MANDATORY_FIELDS_MISSING"


def test_live_view_persistence_failure_does_not_block_rendering(tmp_path):
    database_directory = tmp_path / "database-directory"
    database_directory.mkdir()
    view = build_live_operations_readiness_view(
        FakeDatabase(database_directory),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )
    assert view["confirmed_count"] == 2
    assert view["stages"]["core"]["ready_count"] == 1
    assert view["outcome_persistence"]["status"] == "FAILED"
    assert view["outcome_persistence"]["persisted_count"] == 0
    assert view["outcome_persistence"]["reason"]


def test_live_view_can_disable_persistence_explicitly(tmp_path):
    view = build_live_operations_readiness_view(
        FakeDatabase(tmp_path / "disabled.db"),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        persist_outcomes=False,
    )
    assert view["outcome_persistence"] == {
        "status": "SKIPPED",
        "persisted_count": 0,
        "reason": "PERSISTENCE_DISABLED",
    }
