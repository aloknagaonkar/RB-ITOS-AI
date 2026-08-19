from datetime import datetime

from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2VwapSourceHealth,
)
from red_bar_lab.operations.red_bar_v2_vwap_source import (
    operations_health_row,
    persist_red_bar_v2_vwap_health,
    read_red_bar_v2_vwap_health,
)


def _health():
    stamp = datetime.fromisoformat("2026-08-18T09:29:00+05:30")
    return RedBarV2VwapSourceHealth(
        status="READY",
        reason="FULL_TIMESTAMP_ALIGNMENT",
        price_source_instrument="NSE_INDEX|Nifty 50",
        rsi_source_instrument="NSE_INDEX|Nifty 50",
        vwap_source_instrument="NSE_FO|58072",
        timeframe="1M",
        index_rows=375,
        futures_rows=385,
        aligned_rows=375,
        alignment_coverage_pct=100.0,
        positive_volume_rows=385,
        index_timestamp=stamp,
        futures_timestamp=stamp,
        last_aligned_timestamp=stamp,
    )


def test_health_is_persisted_and_available_for_operations_center(tmp_path):
    path = persist_red_bar_v2_vwap_health(
        _health(),
        artifacts_root=tmp_path,
        trading_date="2026-08-18",
        futures_symbol="NIFTY FUT 25 AUG 26",
        futures_expiry="2026-08-25",
    )

    assert path.exists()
    persisted = read_red_bar_v2_vwap_health(tmp_path)
    assert persisted is not None
    assert persisted.status == "READY"
    assert persisted.payload["aligned_rows"] == 375

    row = operations_health_row(tmp_path)
    assert row["State"] == "HEALTHY"
    assert "NSE_FO|58072" in row["Detail"]
    assert "100.0%" in row["Detail"]


def test_missing_health_record_is_warning(tmp_path):
    row = operations_health_row(tmp_path)
    assert row["State"] == "WARNING"
    assert "No historical replay" in row["Detail"]
