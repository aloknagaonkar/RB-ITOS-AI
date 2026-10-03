from scripts import validate_hilega_wma_delayed_confirmation as m


class Snapshot:
    def __init__(self, rsi, ema, wma):
        self.rsi9 = rsi
        self.ema3_rsi = ema
        self.wma21_rsi = wma
        self.ready = None not in (rsi, ema, wma)


def test_bullish_directional_change_preserves_sign():
    assert m.directional_change(0.75, "BULLISH") == 0.75


def test_bearish_directional_change_normalizes_negative_raw_change():
    assert m.directional_change(-0.75, "BEARISH") == 0.75


def test_confirmation_boundaries_are_exact():
    assert m.confirmation_tier(0.7499, 0.75, 1.0) == "WAIT_DEVELOPING"
    assert m.confirmation_tier(0.75, 0.75, 1.0) == "CONFIRMED_GE_0_75"
    assert m.confirmation_tier(1.0, 0.75, 1.0) == "STRONG_GE_1_00"


def test_wma_confirmation_controls_delayed_entry_not_alignment_diagnostic():
    confirmation = {"minute_timestamp": "2026-10-01T09:30:00+05:30"}
    assert m.delayed_entry_decision(confirmation) == "DELAYED_ENTRY_CONFIRMED"
    assert m.delayed_entry_decision(None) == "NO_ENTRY_BY_T10"


def test_bullish_full_alignment():
    assert m.full_alignment(Snapshot(60, 55, 52), "BULLISH") is True
    assert m.full_alignment(Snapshot(48, 47, 46), "BULLISH") is False


def test_bearish_full_alignment():
    assert m.full_alignment(Snapshot(40, 44, 48), "BEARISH") is True
    assert m.full_alignment(Snapshot(52, 50, 48), "BEARISH") is False


def test_directional_points():
    assert m.directional_points("BULLISH", 100, 112) == 12
    assert m.directional_points("BEARISH", 100, 88) == 12
