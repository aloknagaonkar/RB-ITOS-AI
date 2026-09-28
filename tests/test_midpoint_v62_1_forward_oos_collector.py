from pathlib import Path
from market_lab.midpoint_strategy.forward_oos_v62_1 import MidpointV621ForwardOOSCollector

def test_r1_r2_and_terminal(tmp_path: Path):
    ledger = tmp_path / "ledger.csv"
    c = MidpointV621ForwardOOSCollector(ledger)

    c.on_audit_event({
        "event_type": "CAP20_RESCUE_TRIGGERED",
        "event_timestamp": "2026-09-29T10:00:00+05:30",
        "direction": "BULLISH",
        "underlying_price": 100.0,
        "family": "B",
    })
    c.on_audit_event({
        "event_type": "POST_RESCUE_REENTRY_TRIGGERED",
        "event_timestamp": "2026-09-29T10:05:00+05:30",
        "direction": "BULLISH",
        "underlying_price": 105.0,
        "family": "B",
    })

    c.on_completed_underlying_candle(
        timestamp="2026-09-29T10:06:00+05:30",
        high=126.0, low=118.0, close=124.0
    )
    c.on_completed_underlying_candle(
        timestamp="2026-09-29T10:07:00+05:30",
        high=134.0, low=112.0, close=114.0
    )

    snap = c.active_snapshot()[0]
    assert snap["r1_exit_price"] == 114.0
    assert snap["r2_exit_price"] == 114.0

    c.on_audit_event({
        "event_type": "STRUCTURAL_TERMINAL",
        "event_timestamp": "2026-09-29T10:20:00+05:30",
        "direction": "BULLISH",
        "underlying_price": 90.0,
        "family": "B",
    })

    lines = ledger.read_text().splitlines()
    assert len(lines) == 2
    assert "2026-09-29" in lines[1]
