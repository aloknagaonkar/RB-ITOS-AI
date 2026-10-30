from datetime import datetime
from zoneinfo import ZoneInfo

from market_lab.fixed_strike_oi_fallback_v1 import (
    FixedStrikeOIRow,
    select_exact_strikes_with_oi_fallback,
)

IST = ZoneInfo("Asia/Kolkata")


class PosRow:
    def __init__(self, strike, ce, pe):
        self.strike = strike
        self.ce_open_interest = ce
        self.pe_open_interest = pe


def test_missing_fixed_strike_uses_exact_same_timestamp_option_oi():
    ts = datetime(2026, 5, 4, 13, 30, tzinfo=IST)
    rows = [
        PosRow(24100, 10, 20),
        PosRow(24150, 11, 21),
        PosRow(24200, 12, 22),
        PosRow(24250, 13, 23),
    ]
    idx = {
        (ts, 24300.0): FixedStrikeOIRow(
            strike=24300.0,
            ce_open_interest=14,
            pe_open_interest=24,
        )
    }

    selected = select_exact_strikes_with_oi_fallback(
        rows,
        [24100, 24150, 24200, 24250, 24300],
        timestamp=ts,
        option_oi_index=idx,
    )

    assert [float(r.strike) for r in selected] == [
        24100.0, 24150.0, 24200.0, 24250.0, 24300.0
    ]
    assert selected[-1].ce_open_interest == 14
    assert selected[-1].pe_open_interest == 24
