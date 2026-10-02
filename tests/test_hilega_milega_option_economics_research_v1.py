from datetime import date, datetime, timedelta

from market_lab.domain import IST
from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from market_lab.hilega_milega_option_economics_research_v1 import (
    observe_exact_candidate_economics,
)
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute


def _candidate_set():
    expiry = date(2026, 9, 29)
    contracts = [
        {
            "expiry": expiry.isoformat(),
            "instrument_type": "CE",
            "strike_price": strike,
            "instrument_key": f"CE{strike}",
        }
        for strike in (23300, 23350, 23400, 23450, 23500)
    ]
    return build_bullish_ce_candidate_set(
        signal_spot=23393.25,
        expiry=expiry,
        contracts=contracts,
    )


def _rows(key: str):
    start = datetime(2026, 9, 23, 10, 20, tzinfo=IST)
    out = []
    for i in range(15):
        o = 100.0 + i
        out.append(
            CompletedOptionMinute(
                instrument_key=key,
                timestamp=start + timedelta(minutes=i),
                open=o,
                high=o + 2,
                low=o - 1,
                close=o + 1,
                volume=1000 + i,
            )
        )
    return out


def test_economics_uses_exact_signal_boundary_open_and_no_selection():
    cs = _candidate_set()
    result = observe_exact_candidate_economics(
        signal_bar_ts=datetime(2026, 9, 23, 10, 15, tzinfo=IST),
        candidate_set=cs,
        option_minutes=_rows,
    )
    assert result.status == "AVAILABLE"
    assert result.signal_boundary == "2026-09-23T10:20:00+05:30"
    assert result.selected_instrument_key is None
    assert len(result.candidates) == 5
    for candidate in result.candidates:
        assert candidate.entry_timestamp == "2026-09-23T10:20:00+05:30"
        assert candidate.entry_open == 100.0
        assert [h.horizon_minutes for h in candidate.horizons] == [1, 3, 5, 10, 15]
        assert candidate.horizons[0].exit_timestamp == "2026-09-23T10:20:00+05:30"
        assert candidate.horizons[0].exit_close == 101.0


def test_economics_fails_closed_when_any_exact_minute_missing():
    cs = _candidate_set()

    def rows_missing(key: str):
        return [x for x in _rows(key) if x.timestamp.minute != 24]

    result = observe_exact_candidate_economics(
        signal_bar_ts=datetime(2026, 9, 23, 10, 15, tzinfo=IST),
        candidate_set=cs,
        option_minutes=rows_missing,
    )
    assert result.status == "INCOMPLETE"
    assert result.selected_instrument_key is None
    assert all(c.status == "INCOMPLETE" for c in result.candidates)
    assert all("MISSING_EXACT_MINUTE" in (c.issue or "") for c in result.candidates)


def test_economics_is_blocked_when_candidate_set_is_not_available():
    expiry = date(2026, 9, 29)
    cs = build_bullish_ce_candidate_set(
        signal_spot=23393.25,
        expiry=expiry,
        contracts=[],
    )
    result = observe_exact_candidate_economics(
        signal_bar_ts=datetime(2026, 9, 23, 10, 15, tzinfo=IST),
        candidate_set=cs,
        option_minutes=_rows,
    )
    assert result.status == "BLOCKED"
    assert result.issue == "CANDIDATE_SET_NOT_AVAILABLE"
    assert result.candidates == ()
