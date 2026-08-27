from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.services.red_bar_v2_market_data_evidence import (
    build_candle_pull_evidence,
    persist_market_data_evidence,
    read_market_data_evidence,
)
from red_bar_lab.services.red_bar_v2_live_shadow import (
    build_latest_live_correlation_id,
)
from red_bar_lab.services.red_bar_v2_contract_selection_evidence import (
    ContractCandidateEvidence,
    ContractSelectionEvidence,
    persist_contract_selection_evidence,
    read_contract_selection_evidence,
)
from red_bar_lab.services.red_bar_v2_trade_lifecycle import (
    build_position_snapshot,
    build_trade_lifecycle,
)
from red_bar_lab.services.red_bar_v2_comparison_analytics import (
    build_canonical_performance,
    build_legacy_performance,
)
from red_bar_lab.ui.red_bar_v2_stage_catalog import RED_BAR_V2_STAGES
from red_bar_lab.ui.workspace_page_runtime import PAGE_MODULE_PATHS


EXPECTED = (
    "Input Readiness",
    "Strategy Decision",
    "Signal Bundle",
    "Architecture Parity",
    "Persistence & Integrity",
    "Recent Observations",
    "Process Explanation",
    "Opportunity Queue",
    "Reservation Boundary",
    "Paper Execution",
    "Runtime Health",
    "Provider Readiness",
)


def test_shared_stage_catalog_is_stable_and_ordered():
    assert tuple(stage.number for stage in RED_BAR_V2_STAGES) == tuple(range(1, 13))
    assert tuple(stage.label for stage in RED_BAR_V2_STAGES) == EXPECTED
    assert len({stage.stage_id for stage in RED_BAR_V2_STAGES}) == 12


def test_dual_path_comparison_page_is_registered():
    assert PAGE_MODULE_PATHS["Red Bar V2 Comparison"] == (
        "red_bar_lab.ui.pages.red_bar_v2_comparison"
    )


def test_live_correlation_identity_is_deterministic_for_same_event():
    event = SimpleNamespace(
        timestamp=datetime(2026, 8, 27, 10, 15, tzinfo=ZoneInfo("Asia/Kolkata")),
        event_type="CANDIDATE_ADMISSION",
        admission_code="INITIAL_BEARISH_ALIGNMENT",
        details={"decision_id": "DECISION-1", "reversal_event_id": None},
    )
    monitored = SimpleNamespace(
        replay=SimpleNamespace(trading_date="2026-08-27", events=[event])
    )

    first = build_latest_live_correlation_id(
        monitored=monitored,
        instrument_key="NSE_INDEX|Nifty 50",
    )
    second = build_latest_live_correlation_id(
        monitored=monitored,
        instrument_key="NSE_INDEX|Nifty 50",
    )

    assert first == second
    assert first is not None and first.startswith("RBV2-RUNTIME-")


def test_market_data_evidence_uses_existing_frame_and_explains_gaps(tmp_path):
    requested = datetime(2026, 8, 27, 10, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    received = datetime(2026, 8, 27, 10, 15, 2, tzinfo=ZoneInfo("Asia/Kolkata"))
    frame = pd.DataFrame(
        {
            "timestamp": [
                "2026-08-27T10:11:00+05:30",
                "2026-08-27T10:12:00+05:30",
                "2026-08-27T10:12:00+05:30",
                "2026-08-27T10:14:00+05:30",
            ],
            "close": [100.0, 101.0, 101.0, 102.0],
        }
    )

    evidence = build_candle_pull_evidence(
        frame,
        dataset="NIFTY_INDEX_1M",
        instrument_key="NSE_INDEX|Nifty 50",
        requested_at=requested,
        received_at=received,
        duration_ms=12.3456,
    )

    assert evidence.status == "READY"
    assert evidence.row_count == 4
    assert evidence.duplicate_timestamps == 1
    assert evidence.missing_intervals == 1
    assert evidence.duration_ms == 12.346

    assert persist_market_data_evidence(
        tmp_path,
        (evidence,),
        correlation_id="RBV2-RUNTIME-CORRELATED",
        recorded_at=received,
    ) is True
    restored = read_market_data_evidence(tmp_path)
    assert restored["correlation_id"] == "RBV2-RUNTIME-CORRELATED"
    assert restored["datasets"][0]["reason"] == "COMPLETED_CANDLE_AVAILABLE"


def test_contract_selection_projection_preserves_rank_and_correlation(tmp_path):
    candidate = ContractCandidateEvidence(
        rank=1,
        symbol="NIFTY 24200 PE",
        instrument_token=61670,
        option_type="PE",
        strike=24200.0,
        expiry="2026-09-01",
        lot_size=65,
        total_score=78.5,
        minimum_score=65.0,
        score_eligible=True,
        spread_score=15.0,
        liquidity_score=20.0,
        volume_score=15.0,
        oi_score=10.0,
        vwap_score=10.0,
        ema_score=4.0,
        momentum_score=4.5,
        momentum_pct=0.2,
        candle_count=15,
        ltp=80.0,
        best_bid=79.9,
        best_ask=80.1,
        evidence_detail="completed option candles",
    )
    evidence = ContractSelectionEvidence(
        correlation_id="RBV2-RUNTIME-CORRELATED",
        signal_id="RBV2-SIGNAL-1",
        direction="BEARISH",
        evaluated_at="2026-08-27T10:15:02+05:30",
        duration_ms=12.5,
        candidates=(candidate,),
    )

    assert persist_contract_selection_evidence(
        tmp_path,
        (evidence,),
        recorded_at=datetime(
            2026, 8, 27, 10, 15, 3, tzinfo=ZoneInfo("Asia/Kolkata")
        ),
    ) is True
    restored = read_contract_selection_evidence(tmp_path)
    assert restored["selections"][0]["correlation_id"] == evidence.correlation_id
    assert restored["selections"][0]["candidates"][0]["rank"] == 1


def test_trade_lifecycle_preserves_entry_protection_and_exact_exit_reason():
    signal_id = "RBV2-SIGNAL-1"
    orders = [{
        "signal_id": signal_id,
        "order_id": "PAPER-1",
        "tradingsymbol": "NIFTY 24200 PE",
        "status": "CLOSED",
        "entry_timestamp": "2026-08-27T10:15:03+05:30",
        "entry_price": 80.0,
        "current_price": 86.0,
        "mfe_points": 10.0,
        "mae_points": 2.0,
        "stop_price": 84.0,
        "breakeven_armed": 1,
        "trailing_active": 1,
        "trailing_stop_price": 84.0,
        "exit_action": "EXIT",
        "exit_detail": "protected stop reached",
        "entry_reason": "RED_BAR_V2 approved",
        "exit_timestamp": "2026-08-27T10:20:00+05:30",
        "exit_price": 84.0,
        "exit_reason": "AUTO_TRAILING_STOP",
        "realized_pnl": 260.0,
    }]
    timeline = build_trade_lifecycle(
        signal_id=signal_id,
        state_events=[{
            "signal_id": signal_id,
            "timestamp": "2026-08-27T10:15:00+05:30",
            "state": "APPROVED",
            "detail": "committee approved",
            "order_id": None,
        }],
        queue_rows=[{
            "signal_id": signal_id,
            "created_at": "2026-08-27T10:15:01+05:30",
            "updated_at": "2026-08-27T10:15:02+05:30",
            "status": "EXECUTED",
            "candidate_symbol": "NIFTY 24200 PE",
            "order_id": "PAPER-1",
            "reason": "approved queue item executed",
        }],
        orders=orders,
    )

    assert [row["event"] for row in timeline] == [
        "APPROVED", "QUEUE_CREATED", "QUEUE_UPDATED", "PAPER_ENTRY", "PAPER_EXIT"
    ]
    assert timeline[-1]["reason"] == "AUTO_TRAILING_STOP"
    assert timeline[1]["elapsed_from_previous_ms"] == 1000.0
    positions = build_position_snapshot(orders, signal_id=signal_id)
    assert positions[0]["Trailing active"] is True
    assert positions[0]["Exact exit reason"] == "AUTO_TRAILING_STOP"


def test_bounded_comparison_analytics_separates_paper_pnl_from_shadow():
    signals = [{
        "signal_id": "S1",
        "confirmation_timestamp": "2026-08-27T10:15:00+05:30",
    }, {
        "signal_id": "S2",
        "confirmation_timestamp": "2026-08-27T10:20:00+05:30",
    }]
    orders = [{
        "signal_id": "S1",
        "entry_timestamp": "2026-08-27T10:15:03+05:30",
        "status": "CLOSED",
        "realized_pnl": 260.0,
    }]
    legacy = build_legacy_performance(signals=signals, orders=orders)
    canonical = build_canonical_performance([
        {
            "admission_outcome": "ALLOWED",
            "bundle_available": "YES",
            "parity": "MATCH",
        },
        {
            "admission_outcome": "WAITING",
            "bundle_available": "NO",
            "parity": "MISMATCH",
        },
    ])

    assert legacy["Signal-to-entry conversion %"] == 50.0
    assert legacy["Average signal-to-entry seconds"] == 3.0
    assert legacy["Net realized P&L"] == 260.0
    assert canonical["Admission rate %"] == 50.0
    assert canonical["Parity match rate %"] == 50.0
    assert "Not comparable" in canonical["Paper P&L"]
