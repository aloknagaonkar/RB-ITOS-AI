from types import SimpleNamespace

from red_bar_lab.execution.institutional_execution import InstitutionalExecutionCommittee
from red_bar_lab.execution.paper_engine import PaperContract
from red_bar_lab.execution.performance_selection import (
    HistoricalPerformance,
    PerformanceTradeSelectionEngine,
    TradeSelectionEvaluation,
)
from red_bar_lab.execution.trend_automation import (
    EMA10OpportunityIntelligenceEngine,
    TrendAwareDatabaseProxy,
)


def _candidate(*, option_type="PE", total=90.0, spread=15.0, liquidity=20.0):
    return SimpleNamespace(
        contract=PaperContract(
            instrument_token=101,
            tradingsymbol=f"NIFTYTEST{option_type}",
            exchange="NFO",
            option_type=option_type,
            strike=24400.0,
            expiry="2026-08-13",
            lot_size=75,
        ),
        total_score=total,
        spread_score=spread,
        liquidity_score=liquidity,
        volume_score=15.0,
        oi_score=10.0,
        vwap_score=10.0,
        ema_score=10.0,
        momentum_score=10.0,
    )


def _signal(direction, close, ema10):
    return {
        "signal_id": "S1",
        "direction": direction,
        "confirmation_high": 110.0,
        "confirmation_low": 90.0,
        "confirmation_close": 100.0,
        "underlying_entry": 100.0,
        "_ema10_5m_ready": True,
        "_ema10_5m_close": close,
        "_ema10_5m_value": ema10,
    }


def test_change1_reward_consumed_no_longer_blocks_when_bearish_ema10_holds():
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)
    result = engine.evaluate(
        signal=_signal("BEARISH", 80.0, 85.0),
        candidate=_candidate(),
        spot_price=50.0,
        signal_age_seconds=900,
        opposite_red_bar_confirmed=False,
    )
    assert result.reward_remaining_pct == 0.0
    assert result.move_consumed_pct == 100.0
    assert result.eligible is True
    assert "REWARD_CONSUMED" not in result.reason
    assert "EMA10_TREND_VALID" in result.reason


def test_change1_bearish_ema10_loss_blocks_new_pe_entry():
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)
    result = engine.evaluate(
        signal=_signal("BEARISH", 86.0, 85.0),
        candidate=_candidate(),
        spot_price=80.0,
        signal_age_seconds=300,
        opposite_red_bar_confirmed=False,
    )
    assert result.eligible is False
    assert result.reason == "BEARISH_EMA10_LOST"


def test_change1_bullish_ema10_loss_blocks_new_ce_entry():
    engine = EMA10OpportunityIntelligenceEngine(minimum_opportunity_score=0)
    result = engine.evaluate(
        signal=_signal("BULLISH", 99.0, 100.0),
        candidate=_candidate(option_type="CE"),
        spot_price=105.0,
        signal_age_seconds=300,
        opposite_red_bar_confirmed=False,
    )
    assert result.eligible is False
    assert result.reason == "BULLISH_EMA10_LOST"


def test_change2_reward_risk_does_not_change_selection_score():
    engine = PerformanceTradeSelectionEngine(minimum_selection_score=0)
    opportunity = SimpleNamespace(
        opportunity_score=80.0,
        reward_remaining_pct=5.0,
        eligible=True,
        reason="OPPORTUNITY_HEALTH_PASS | EMA10_TREND_VALID",
    )
    common = dict(
        candidate=_candidate(total=80.0),
        candidate_rank=1,
        opportunity=opportunity,
        historical_orders=[],
        entry_mode="FRESH_SIGNAL",
        minimum_candidate_score=65.0,
        stop_loss_pct=15.0,
        require_opportunity_gate=False,
    )
    normal = engine.evaluate(target_pct=25.0, **common)
    extreme = engine.evaluate(target_pct=300.0, **common)
    assert normal.reward_risk_ratio != extreme.reward_risk_ratio
    assert normal.selection_score == extreme.selection_score
    assert "REWARD_RISK_INFORMATIONAL_ONLY" in normal.reason


def _history():
    return HistoricalPerformance(
        sample_size=0,
        wins=0,
        losses=0,
        win_rate_pct=None,
        average_return_pct=None,
        average_winner_pct=None,
        average_loser_pct=None,
        profit_factor=None,
        expectancy_pct=None,
        average_mfe_pct=None,
        average_mae_pct=None,
        evidence_ready=False,
    )


def test_change3_negative_expectancy_is_informational_only():
    selection = TradeSelectionEvaluation(
        candidate_rank=1,
        candidate_symbol="NIFTYTESTPE",
        candidate_score=80.0,
        opportunity_score=80.0,
        reward_remaining_pct=100.0,
        reward_risk_ratio=0.02,
        execution_quality_score=100.0,
        historical_score=50.0,
        selection_score=80.0,
        historical=_history(),
        eligible=True,
        decision="BUY PE",
        reason="NO_HARD_PERFORMANCE_BLOCKERS",
    )
    opportunity = SimpleNamespace(
        opportunity_score=80.0,
        reward_remaining_pct=100.0,
        eligible=True,
        reason="OPPORTUNITY_HEALTH_PASS | EMA10_TREND_VALID",
    )
    committee = InstitutionalExecutionCommittee(
        minimum_execution_probability_pct=0,
        minimum_expected_value_pct=9999.0,
    )
    result = committee.evaluate(
        candidate=_candidate(total=80.0),
        selection=selection,
        opportunity=opportunity,
        historical_orders=[],
        current_shadow=None,
        historical_shadow=[],
        stop_loss_pct=50.0,
        target_pct=1.0,
    )
    assert result.expectancy_pct < 0
    assert result.expected_value_pct == 0.0
    assert result.eligible is True
    assert "EXPECTANCY=" not in result.reason


class _FakeDatabase:
    def __init__(self, open_rows=None, queue_rows=None):
        self.open_rows = open_rows or []
        self.queue_rows = queue_rows or []

    def read_open_paper_execution_orders(self, account_id):
        return list(self.open_rows)

    def read_execution_queue(self, **kwargs):
        return list(self.queue_rows)


def _trend():
    return SimpleNamespace(
        ready=True,
        close=100.0,
        ema10=101.0,
        timestamp="2026-08-12T10:00:00+05:30",
        reason="READY",
    )


def test_change4_same_contract_open_is_duplicate_across_signals():
    db = _FakeDatabase(open_rows=[{"instrument_token": 101, "status": "OPEN"}])
    proxy = TrendAwareDatabaseProxy(db, _trend)
    assert proxy.paper_execution_exists_for_candidate(
        signal_id="NEW-SIGNAL", account_id="PAPER-STD", instrument_token=101
    ) is True


def test_change4_pending_contract_from_other_signal_is_duplicate():
    db = _FakeDatabase(queue_rows=[{
        "instrument_token": 101,
        "status": "APPROVED",
        "signal_id": "OTHER-SIGNAL",
    }])
    proxy = TrendAwareDatabaseProxy(db, _trend)
    assert proxy.paper_execution_exists_for_candidate(
        signal_id="S1", account_id="PAPER-STD", instrument_token=101
    ) is True


def test_change4_own_approved_queue_row_does_not_self_block_execution():
    db = _FakeDatabase(queue_rows=[{
        "instrument_token": 101,
        "status": "APPROVED",
        "signal_id": "S1",
    }])
    proxy = TrendAwareDatabaseProxy(db, _trend)
    assert proxy.paper_execution_exists_for_candidate(
        signal_id="S1", account_id="PAPER-STD", instrument_token=101
    ) is False


def test_change4_closed_contract_can_be_reconsidered():
    db = _FakeDatabase(queue_rows=[{
        "instrument_token": 101,
        "status": "CLOSED",
        "signal_id": "S1",
    }])
    proxy = TrendAwareDatabaseProxy(db, _trend)
    assert proxy.paper_execution_exists_for_candidate(
        signal_id="S1", account_id="PAPER-STD", instrument_token=101
    ) is False
