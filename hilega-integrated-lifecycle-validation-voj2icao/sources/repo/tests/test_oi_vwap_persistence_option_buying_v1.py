
from market_lab.oi_vwap_persistence_option_buying_v1 import (
    OICheckpoint, VWAPContext, OIVWAPPersistenceStrategyV1,
    Decision
)
from market_lab.oi_vwap_persistence_paper_risk_v1 import PremiumExitState, ExitDecision


def oi(ts, prev_imb, cur_imb, pcr, prev_sess, cur_sess):
    return OICheckpoint(
        timestamp=ts,
        previous_imbalance_5m=prev_imb,
        current_imbalance_5m=cur_imb,
        pcr_change_5m=pcr,
        previous_session_imbalance=prev_sess,
        current_session_imbalance=cur_sess,
        ce_delta_5m=0,
        pe_delta_5m=0,
    )


def test_bullish_p1_waits_for_p2_then_enters_ce():
    s = OIVWAPPersistenceStrategyV1()
    p1 = oi("2026-09-16T10:20:00+05:30", -1_000_000, 2_000_000, 0.04, -5_000_000, -2_000_000)
    vw = VWAPContext("10:15", "10:20", 25010, 25000)

    r1 = s.on_p1_checkpoint(p1, vw)
    assert r1.decision == Decision.WAIT_P2

    p2 = oi("2026-09-16T10:25:00+05:30", 2_000_000, 1_500_000, 0.02, -2_000_000, -1_000_000)
    r2 = s.on_p2_checkpoint(
        p2,
        exact_atm_strike=25000,
        exact_atm_quote_available=True,
    )
    assert r2.decision == Decision.ENTER_CE_PAPER
    assert s.state.open_position_count == 1


def test_bearish_p1_waits_for_p2_then_enters_pe():
    s = OIVWAPPersistenceStrategyV1()
    p1 = oi("2026-09-16T11:00:00+05:30", 500_000, -2_000_000, -0.03, 4_000_000, 1_000_000)
    vw = VWAPContext("10:55", "11:00", 24980, 25000)

    assert s.on_p1_checkpoint(p1, vw).decision == Decision.WAIT_P2

    p2 = oi("2026-09-16T11:05:00+05:30", -2_000_000, -1_000_000, -0.02, 1_000_000, 0)
    r = s.on_p2_checkpoint(p2, exact_atm_strike=25000, exact_atm_quote_available=True)
    assert r.decision == Decision.ENTER_PE_PAPER


def test_vwap_misalignment_rejects():
    s = OIVWAPPersistenceStrategyV1()
    p1 = oi("2026-09-16T10:20:00+05:30", -1, 1, 0.01, -10, -5)
    vw = VWAPContext("10:15", "10:20", 24990, 25000)
    assert s.on_p1_checkpoint(p1, vw).decision == Decision.NO_TRADE


def test_max_four_positions():
    s = OIVWAPPersistenceStrategyV1()
    s.state.open_position_count = 4
    p1 = oi("2026-09-16T10:20:00+05:30", -1, 1, 0.01, -10, -5)
    vw = VWAPContext("10:15", "10:20", 25010, 25000)
    assert s.on_p1_checkpoint(p1, vw).decision == Decision.WAIT_P2
    p2 = oi("2026-09-16T10:25:00+05:30", 1, 2, 0.01, -5, -4)
    assert s.on_p2_checkpoint(p2, exact_atm_strike=25000, exact_atm_quote_available=True).decision == Decision.CAPACITY_REJECTED
    assert s.state.open_position_count == 4


def test_no_max_holding_time_constant():
    from market_lab.oi_vwap_persistence_option_buying_v1 import MAX_HOLDING_MINUTES
    assert MAX_HOLDING_MINUTES is None


def test_premium_exit_has_no_time_exit():
    e = PremiumExitState(100.0)
    assert e.evaluate(94.9) == ExitDecision.STOP_LOSS

    e = PremiumExitState(100.0)
    assert e.evaluate(106.0) == ExitDecision.HOLD
    assert e.breakeven_active is True
    assert e.evaluate(100.0) == ExitDecision.BREAKEVEN

    e = PremiumExitState(100.0)
    assert e.evaluate(112.0) == ExitDecision.HOLD
    assert e.trailing_active is True
    assert e.evaluate(108.5) == ExitDecision.TRAILING_STOP
