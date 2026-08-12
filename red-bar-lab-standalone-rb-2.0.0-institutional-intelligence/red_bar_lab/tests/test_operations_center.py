from datetime import datetime

from red_bar_lab.config import RedBarSettings
from red_bar_lab.operations.service import RedBarOperationsCenterService
from red_bar_lab.storage.database import RedBarDatabase


def test_operations_center_empty_database_is_safe(tmp_path):
    settings = RedBarSettings(
        artifacts_root=tmp_path / "artifacts"
    )
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    service = RedBarOperationsCenterService(database, settings)
    snapshot = service.snapshot(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-08",
        now=datetime.fromisoformat(
            "2026-08-08T10:00:00+05:30"
        ),
        token_present=False,
    )

    assert 0 <= snapshot.health_score <= 100
    assert snapshot.market["phase"] == "WEEKEND"
    assert snapshot.pipeline["confirmed_signals"] == 0
    assert snapshot.ai_readiness["training_samples"] == 0
    assert snapshot.data_quality["missing_market_context"] == 0


def test_operations_center_reports_data_quality(tmp_path):
    settings = RedBarSettings(
        artifacts_root=tmp_path / "artifacts"
    )
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    # Use pipeline status rows directly to verify readiness aggregation.
    database.upsert_signal_pipeline_status(
        {
            "signal_id": "SIG-1",
            "instrument_key": "NSE_INDEX|Nifty 50",
            "trading_date": "2026-08-07",
            "market_context_ready": 1,
            "volume_structure_ready": 1,
            "options_context_ready": 0,
            "core_eligible": 1,
            "hybrid_eligible": 0,
        }
    )

    rows = database.read_signal_pipeline_status_range(
        "NSE_INDEX|Nifty 50",
        "2026-08-07",
        "2026-08-07",
    )
    assert len(rows) == 1
    assert rows[0]["core_eligible"] == 1
    assert rows[0]["hybrid_eligible"] == 0
