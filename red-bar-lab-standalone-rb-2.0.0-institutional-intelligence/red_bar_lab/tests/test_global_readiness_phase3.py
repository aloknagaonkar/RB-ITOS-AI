from pathlib import Path
from types import SimpleNamespace

from red_bar_lab.services.global_readiness import assess_global_readiness
from red_bar_lab.services.global_readiness_runtime import build_and_persist_global_readiness
from red_bar_lab.services.global_readiness_store import (
    persist_global_readiness_snapshot,
    read_global_readiness_snapshots,
)
from red_bar_lab.services.global_readiness_validation import (
    build_global_readiness_shadow_report,
    replay_global_readiness,
)


def _ready():
    return assess_global_readiness(
        underlying_candle="READY",
        option_chain="READY",
        option_quotes="READY",
        pcr="READY",
        futures="READY",
        futures_strength="STRONG",
        v2_alignment="ALIGNED",
        execution_source="ENABLED",
        market_hours="OPEN",
    )


def test_snapshot_persistence_is_idempotent_and_observational(tmp_path: Path):
    path = tmp_path / "readiness.sqlite3"
    for timestamp in ("2026-08-20 15:39:00+05:30", "2026-08-20T15:39:00+05:30"):
        persist_global_readiness_snapshot(
            path,
            observed_at=timestamp,
            underlying_name="NIFTY 50",
            instrument_key="NSE_INDEX|Nifty 50",
            readiness=_ready(),
            signals_seen=2,
            signals_scored=1,
        )
    rows = read_global_readiness_snapshots(path, underlying_name="NIFTY 50")
    assert len(rows) == 1
    assert rows[0]["observed_at"] == "2026-08-20T15:39:00+05:30"
    assert rows[0]["authority"] == "OBSERVATIONAL_ONLY"


def test_shadow_report_correlates_signals_orders_and_outcomes():
    rows = [
        {"overall_status": "READY", "signals_seen": 2, "signals_scored": 1, "orders_opened": 1, "orders_skipped": 1, "trade_outcome": "WIN"},
        {"overall_status": "BLOCKED", "signals_seen": 1, "signals_scored": 0, "orders_opened": 0, "orders_skipped": 1, "trade_outcome": "LOSS"},
    ]
    report = build_global_readiness_shadow_report(rows)
    assert report.observations == 2
    assert report.ready_rate_pct == 50.0
    assert report.signals_seen == 3
    assert report.orders_opened == 1
    assert report.successful_trades == 1


def test_historical_replay_counts_component_and_reason_frequency():
    rows = [
        {
            "overall_status": "DEGRADED",
            "underlying_status": "READY",
            "option_chain_status": "PARTIAL",
            "option_quote_status": "STALE",
            "pcr_status": "READY",
            "futures_status": "READY",
            "v2_alignment_status": "ALIGNED",
            "execution_source_status": "ENABLED",
            "market_hours_status": "MARKET_CLOSED",
            "blocking_reasons": [],
            "advisory_reasons": ["OPTION_CHAIN_PARTIAL", "OPTION_QUOTE_STALE"],
            "trade_outcome": "UNKNOWN",
        }
    ]
    replay = replay_global_readiness(rows)
    assert replay.status_counts["DEGRADED"] == 1
    assert replay.component_failure_counts["option_chain_status:PARTIAL"] == 1
    assert replay.advisory_reason_counts["OPTION_CHAIN_PARTIAL"] == 1


def test_runtime_adapter_introduces_no_market_calls():
    from red_bar_lab.services import global_readiness_runtime

    source = global_readiness_runtime.build_and_persist_global_readiness.__doc__
    assert "no market-data calls" in source


def test_after_hours_missing_quotes_pcr_and_stale_bridge_are_advisory(tmp_path: Path):
    result = build_and_persist_global_readiness(
        database_path=tmp_path / "readiness.sqlite3",
        observed_at="2026-08-20T22:48:53+05:30",
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        candle_diagnostic=SimpleNamespace(
            readiness=SimpleNamespace(status="MARKET_CLOSED")
        ),
        futures_readiness=SimpleNamespace(status="READY"),
        futures_strength=SimpleNamespace(strength="WEAK"),
        bridge=SimpleNamespace(status="BLOCKED", reason="V2_SNAPSHOT_STALE"),
        authority=SimpleNamespace(source_enabled=True),
        latest_signal_diagnostic={
            "market_hours_ok": False,
            "option_chain_status": "READY",
        },
        report=SimpleNamespace(
            signals_seen=55,
            candidates_scored=0,
            paper_orders_opened=0,
            skipped=53,
        ),
    )

    assert result.status == "DEGRADED"
    assert result.blocking_reasons == ()
    assert result.option_quote_status == "MARKET_CLOSED"
    assert result.pcr_status == "MARKET_CLOSED"
    assert result.v2_alignment_status == "AFTER_HOURS_EXPECTED"
    assert "FUTURES_STRENGTH_WEAK" in result.advisory_reasons
    assert result.execution_reasons == ("MARKET_HOURS_OUTSIDE_ENTRY_HOURS",)
