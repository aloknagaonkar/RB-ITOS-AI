from red_bar_lab.services.signal_enrichment_outcome_store import (
    persist_signal_enrichment_outcomes,
)
from red_bar_lab.ui.operations_readiness_wrapper import (
    build_live_operations_readiness_view,
)


class DiagnosticDatabase:
    def __init__(self, path):
        self.path = path

    def read_signal_attempts(self, instrument_key, trading_date):
        return [
            {
                "signal_id": "RBV2-1",
                "confirmation_timestamp": "2026-08-21T10:20:00+05:30",
            }
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
        return [{"signal_id": "RBV2-1"}]

    def read_volume_structure_snapshots(self, instrument_key, start, end):
        return [{"signal_id": "RBV2-1"}]

    def read_option_context_snapshots(self, instrument_key, start, end):
        return [{"signal_id": "RBV2-1", "entry_aligned": 1}]

    def read_option_context_by_signal(self, signal_id):
        return None


def test_live_view_uses_latest_persisted_market_and_volume_diagnostics(tmp_path):
    database_path = tmp_path / "operations.db"
    persist_signal_enrichment_outcomes(
        database_path,
        (
            {
                "signal_id": "RBV2-1",
                "strategy_id": "RED_BAR_V2",
                "stage": "MARKET",
                "status": "READY",
                "input_source": "LIVE_PERSISTED",
                "input_cutoff_timestamp": "2026-08-21T10:20:00+05:30",
                "latest_source_timestamp": "2026-08-21T10:19:00+05:30",
                "no_lookahead_passed": True,
                "attempt_timestamp": "2026-08-21T10:20:01+05:30",
                "fallback_used": False,
                "row_count": 65,
            },
            {
                "signal_id": "RBV2-1",
                "strategy_id": "RED_BAR_V2",
                "stage": "VOLUME",
                "status": "READY",
                "input_source": "HISTORICAL_REPOSITORY",
                "input_cutoff_timestamp": "2026-08-21T10:20:00+05:30",
                "latest_source_timestamp": "2026-08-21T10:19:00+05:30",
                "no_lookahead_passed": True,
                "attempt_timestamp": "2026-08-21T10:20:02+05:30",
                "fallback_used": True,
                "row_count": 65,
            },
        ),
    )

    view = build_live_operations_readiness_view(
        DiagnosticDatabase(database_path),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        persist_outcomes=False,
    )

    row = view["drilldown"][0]
    assert row["Market source"] == "LIVE_PERSISTED"
    assert row["Market rows"] == 65
    assert row["Market fallback"] == "NO"
    assert row["Market no-lookahead"] == "YES"
    assert row["Volume source"] == "HISTORICAL_REPOSITORY"
    assert row["Volume rows"] == 65
    assert row["Volume fallback"] == "YES"
    assert row["Volume no-lookahead"] == "YES"
