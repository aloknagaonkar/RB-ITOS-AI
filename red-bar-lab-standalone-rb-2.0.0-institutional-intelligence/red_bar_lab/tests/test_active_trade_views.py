from red_bar_lab.ui.active_trade_views import _is_duplicate


def test_duplicate_rows_are_hidden_from_active_views():
    assert _is_duplicate({"duplicate": 1}) is True
    assert _is_duplicate({"status": "ARCHIVED"}) is True
    assert _is_duplicate({"reason": "DUPLICATE_TRADE"}) is True


def test_normal_active_rows_remain_visible():
    assert _is_duplicate({"status": "APPROVED", "reason": "READY"}) is False
