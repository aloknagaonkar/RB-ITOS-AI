from datetime import datetime

from red_bar_lab.services.option_participation import build_option_participation_summary
from red_bar_lab.services.option_participation_store import (
    persist_option_participation,
    read_latest_option_participation,
    summarize_option_participation,
)


def _row(side, strike, premium_change, oi_change, volume, score_inputs=True):
    return {
        "distance_rank": 1,
        "instrument_key": f"KEY-{side}-{strike}",
        "instrument_token": int(strike),
        "tradingsymbol": f"NIFTY{int(strike)}{side}",
        "option_type": side,
        "strike": float(strike),
        "expiry": "2026-08-27",
        "lot_size": 75,
        "current_price": 120.0 if side == "CE" else 95.0,
        "vwap": 110.0 if score_inputs else None,
        "premium_change_pct": premium_change,
        "volume": volume,
        "contract_volume": volume / 75.0,
        "oi": 500000.0,
        "prev_oi": 450000.0,
        "oi_change": oi_change,
        "oi_change_pct": oi_change / 450000.0 * 100.0,
        "delta": 0.52 if side == "CE" else -0.48,
        "iv": 13.5,
        "option_rsi": 61.0 if score_inputs else None,
        "underlying_rsi": 59.0,
        "bid": 119.5,
        "ask": 120.5,
        "spread": 1.0,
    }


def test_ce_fresh_buying_dominance_recommends_ce():
    rows = [
        _row("CE", 24300, 8.0, 70000, 180000),
        {**_row("CE", 24350, 5.0, 45000, 130000), "distance_rank": 2},
        {**_row("CE", 24400, 3.0, 25000, 90000), "distance_rank": 3},
        _row("PE", 24300, -4.0, 80000, 150000),
        {**_row("PE", 24250, -3.0, 50000, 100000), "distance_rank": 2},
        {**_row("PE", 24200, -2.0, 30000, 80000), "distance_rank": 3},
    ]
    summary = build_option_participation_summary(
        observed_at=datetime(2026, 8, 21, 10, 30),
        underlying_name="NIFTY 50",
        spot_price=24287.0,
        expiry="2026-08-27",
        pcr_oi=0.91,
        underlying_rsi=59.0,
        rows=rows,
    )
    assert summary.recommended_side == "CE"
    assert summary.recommended_direction == "BULLISH"
    assert summary.ce_score > summary.pe_score
    assert all(row["participation_state"] == "FRESH_BUYING" for row in summary.rows[:3])
    assert all(row["participation_state"] == "WRITING_PRESSURE" for row in summary.rows[3:])


def test_close_ce_pe_scores_produce_wait():
    ce_rows = [
        _row("CE", 24300, 3.0, 30000, 100000),
        {**_row("CE", 24350, 2.0, 20000, 90000), "distance_rank": 2},
        {**_row("CE", 24400, 1.0, 10000, 80000), "distance_rank": 3},
    ]
    pe_rows = [
        _row("PE", 24300, 3.0, 30000, 100000),
        {**_row("PE", 24250, 2.0, 20000, 90000), "distance_rank": 2},
        {**_row("PE", 24200, 1.0, 10000, 80000), "distance_rank": 3},
    ]
    # Keep PE premiums realistic while making the score evidence symmetric:
    # both CE and PE rows are above their own option VWAP, with matching
    # participation state, volume, OI change, RSI and Delta quality bands.
    pe_rows = [{**row, "vwap": 90.0} for row in pe_rows]

    summary = build_option_participation_summary(
        observed_at="2026-08-21T10:30:00+05:30",
        underlying_name="NIFTY 50",
        spot_price=24287.0,
        expiry="2026-08-27",
        pcr_oi=1.0,
        underlying_rsi=50.0,
        rows=ce_rows + pe_rows,
    )
    assert summary.ce_score == summary.pe_score
    assert summary.recommended_side == "WAIT"
    assert summary.recommended_direction == "NEUTRAL"
    assert summary.grade == "CONFLICTED"


def test_participation_store_keeps_six_rows_and_totals(tmp_path):
    rows = [
        {**_row("CE", 24300, 5.0, 50000, 150000), "distance_rank": 1},
        {**_row("CE", 24350, 4.0, 40000, 120000), "distance_rank": 2},
        {**_row("CE", 24400, 3.0, 30000, 90000), "distance_rank": 3},
        {**_row("PE", 24300, -2.0, 60000, 160000), "distance_rank": 1},
        {**_row("PE", 24250, -2.0, 50000, 130000), "distance_rank": 2},
        {**_row("PE", 24200, -1.0, 40000, 100000), "distance_rank": 3},
    ]
    summary = build_option_participation_summary(
        observed_at="2026-08-21T10:30:00+05:30",
        underlying_name="NIFTY 50",
        spot_price=24287.0,
        expiry="2026-08-27",
        pcr_oi=1.08,
        underlying_rsi=57.0,
        rows=rows,
    )
    db = tmp_path / "rb.sqlite"
    assert persist_option_participation(db, summary) == 6
    stored = read_latest_option_participation(db)
    assert len(stored) == 6
    totals = summarize_option_participation(stored)
    assert totals["ce_total_volume"] == 360000.0
    assert totals["pe_total_volume"] == 390000.0
    assert totals["ce_total_oi_change"] == 120000.0
    assert totals["pe_total_oi_change"] == 150000.0
    assert totals["ce_weighted_delta"] > 0
    assert totals["pe_weighted_delta"] < 0
    assert totals["authority"] == "OBSERVATIONAL_ONLY"
