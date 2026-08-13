from red_bar_lab.ui.active_trade_views import (
    _compact_exit_rows,
    _compact_queue_rows,
    _compact_rank_rows,
    _compact_trade_rows,
    _is_duplicate,
)


def test_duplicate_rows_are_hidden_from_active_views():
    assert _is_duplicate({"duplicate": 1}) is True
    assert _is_duplicate({"status": "ARCHIVED"}) is True
    assert _is_duplicate({"reason": "DUPLICATE_TRADE"}) is True


def test_normal_active_rows_remain_visible():
    assert _is_duplicate({"status": "APPROVED", "reason": "READY"}) is False


def test_compact_trade_view_keeps_only_operational_columns():
    rows = _compact_trade_rows([
        {
            "order_id": "O1",
            "tradingsymbol": "NIFTY24500CE",
            "option_type": "CE",
            "quantity": 75,
            "entry_price": 100.0,
            "current_price": 110.0,
            "unrealized_pnl": 750.0,
            "entry_timestamp": "2026-08-13T10:00:00+05:30",
            "entry_reason": "COMMITTEE_APPROVED",
            "internal_debug_field": "HIDE",
        }
    ])
    assert rows[0]["Order"] == "O1"
    assert rows[0]["P&L"] == 750.0
    assert "internal_debug_field" not in rows[0]


def test_compact_rank_queue_and_exit_views_remove_debug_noise():
    rank = _compact_rank_rows([
        {
            "candidate_rank": 1,
            "candidate_symbol": "NIFTY24500CE",
            "candidate_score": 91.0,
            "opportunity_score": 88.0,
            "selection_score": 90.0,
            "eligible": 1,
            "reason": "READY",
            "expert_votes": ["hidden"],
        }
    ])
    queue = _compact_queue_rows([
        {
            "candidate_rank": 1,
            "candidate_symbol": "NIFTY24500CE",
            "direction": "BULLISH",
            "status": "APPROVED",
            "reason": "READY",
            "order_id": None,
            "updated_at": "NOW",
            "candidate_score": 91.0,
        }
    ])
    exits = _compact_exit_rows([
        {
            "order_id": "O1",
            "tradingsymbol": "NIFTY24500CE",
            "entry_price": 100.0,
            "exit_price": 120.0,
            "realized_pnl": 1500.0,
            "exit_timestamp": "NOW",
            "exit_reason": "EMA10_EXIT",
            "mfe_points": 25.0,
        }
    ])

    assert rank[0]["Execute"] == "YES"
    assert "expert_votes" not in rank[0]
    assert queue[0]["Status"] == "APPROVED"
    assert "candidate_score" not in queue[0]
    assert exits[0]["Exit Reason"] == "EMA10_EXIT"
    assert "mfe_points" not in exits[0]
