from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.services.trade_candidate_snapshot_store import (
    persist_trade_candidate_snapshots,
    read_latest_trade_candidates,
)

IST = ZoneInfo("Asia/Kolkata")


def _candidate(index: int, price: float) -> dict[str, object]:
    return {
        "tradingsymbol": f"NIFTY TEST {index} CE",
        "option_type": "CE",
        "strike": 24000 + index * 50,
        "expiry": "2026-08-25",
        "current_price": price,
        "vwap": price - 2.0,
        "candidate_score": 90.0 - index,
        "lot_size": 65,
    }


def test_persists_five_and_tracks_frozen_recommendation_price(tmp_path):
    database = tmp_path / "test.sqlite"
    first_time = datetime(2026, 8, 21, 10, 0, tzinfo=IST)
    second_time = datetime(2026, 8, 21, 10, 5, tzinfo=IST)

    assert persist_trade_candidate_snapshots(
        database,
        observed_at=first_time,
        underlying_name="NIFTY 50",
        recommendation_source="INDEPENDENT_MARKET",
        direction="BULLISH",
        candidates=[_candidate(index, 100.0 + index) for index in range(1, 7)],
    ) == 5

    assert persist_trade_candidate_snapshots(
        database,
        observed_at=second_time,
        underlying_name="NIFTY 50",
        recommendation_source="INDEPENDENT_MARKET",
        direction="BULLISH",
        candidates=[_candidate(index, 110.0 + index) for index in range(1, 6)],
    ) == 5

    rows = read_latest_trade_candidates(database, limit=5)
    assert len(rows) == 5
    first = rows[0]
    assert first["recommendation_at"] == first_time.isoformat()
    assert first["recommendation_price"] == 101.0
    assert first["current_price"] == 111.0
    assert first["best_price"] == 111.0
    assert round(first["move_points"], 2) == 10.0
    assert round(first["move_pct"], 2) == round(10.0 / 101.0 * 100.0, 2)
    assert round(first["max_move_pct"], 2) == round(10.0 / 101.0 * 100.0, 2)
