from backend.market_lab.cross_date_transition_extractor_v1 import (
    _horizon_state,
    _three_horizon_state,
    build_transition_row,
    extract_runs,
)


def test_horizon_state():
    assert _horizon_state(1.0, 0.1) == "BULLISH"
    assert _horizon_state(-1.0, -0.1) == "BEARISH"
    assert _horizon_state(1.0, -0.1) == "MIXED"
    assert _horizon_state(None, 0.1) == "NA"


def test_three_horizon_state():
    assert _three_horizon_state("BULLISH", "BULLISH", "BULLISH") == "BULLISH_ALL_3"
    assert _three_horizon_state("BEARISH", "BEARISH", "BEARISH") == "BEARISH_ALL_3"
    assert _three_horizon_state("BULLISH", "BEARISH", "BULLISH") == "MIXED"
    assert _three_horizon_state("NA", "BULLISH", "BULLISH") == "INCOMPLETE"


def _row(ts, i5, p5, i10, p10, i15, p15):
    return build_transition_row("2026-01-01", {
        "timestamp": ts,
        "imbalance_5m": i5,
        "pcr_change_5m": p5,
        "imbalance_10m": i10,
        "pcr_change_10m": p10,
        "imbalance_15m": i15,
        "pcr_change_15m": p15,
    })


def test_runs_are_split_by_mixed_candle():
    rows = [
        _row("09:30", 1, 1, 1, 1, 1, 1),
        _row("09:35", 1, 1, 1, 1, 1, 1),
        _row("09:40", 1, 1, -1, -1, 1, 1),
        _row("09:45", -1, -1, -1, -1, -1, -1),
    ]
    runs = extract_runs(rows)
    assert len(runs) == 2
    assert runs[0].direction == "BULLISH"
    assert runs[0].candles == 2
    assert runs[1].direction == "BEARISH"
    assert runs[1].candles == 1


def test_counts_preserve_mixed_information():
    r = _row("10:00", 1, 1, -1, -1, 1, -1)
    assert r.bullish_horizon_count == 1
    assert r.bearish_horizon_count == 1
    assert r.three_horizon_state == "MIXED"
