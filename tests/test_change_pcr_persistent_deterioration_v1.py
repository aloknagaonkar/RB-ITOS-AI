from market_lab.change_pcr_persistent_deterioration_v1 import (
    normalized_oi_dominance,
    directional_move,
)


def test_normalized_dominance():
    assert normalized_oi_dominance(10, 20) == 1/3
    assert normalized_oi_dominance(20, 10) == -1/3
    assert normalized_oi_dominance(-10, 20) == 1.0
    assert normalized_oi_dominance(10, -20) == -1.0


def test_directional_move():
    assert directional_move(0.2, "BULLISH") is True
    assert directional_move(-0.2, "BEARISH") is True
    assert directional_move(-0.2, "BULLISH") is False
    assert directional_move(0.2, "BEARISH") is False
    assert directional_move(None, "BULLISH") is False
