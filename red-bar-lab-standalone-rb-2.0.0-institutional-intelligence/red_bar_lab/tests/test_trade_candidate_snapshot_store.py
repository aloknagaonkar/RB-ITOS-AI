from red_bar_lab.services.trade_candidate_snapshot_store import (
    persist_trade_candidate_snapshots,
    read_latest_trade_candidates,
)


def test_persists_only_top_three_with_vwap_pcr_and_rsi(tmp_path):
    path = tmp_path / "lab.db"
    candidates = [
        {
            "tradingsymbol": f"NIFTY-{index}-CE",
            "option_type": "CE",
            "strike": 24000 + (index * 50),
            "expiry": "2026-08-27",
            "current_price": 100 + index,
            "vwap": 98 + index,
            "delta": 0.50 + (index / 100),
            "pcr_oi": 0.82,
            "pcr_view": "SUPPORTIVE",
            "underlying_rsi": 62.4,
            "option_rsi": 55 + index,
            "rsi_view": "SUPPORTIVE",
            "candidate_score": 90 - index,
            "lot_size": 75,
            "evidence_grade": "STRONG",
            "suggested_action": "PAPER OBSERVATION",
        }
        for index in range(1, 5)
    ]

    assert persist_trade_candidate_snapshots(
        path,
        observed_at="2026-08-20T10:25:00+05:30",
        underlying_name="NIFTY 50",
        recommendation_source="INDEPENDENT_MARKET",
        direction="BULLISH",
        candidates=candidates,
    ) == 3

    rows = read_latest_trade_candidates(path)
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert [row["role"] for row in rows] == ["PRIMARY", "SAFER", "AGGRESSIVE"]
    assert rows[0]["current_price"] == 101.0
    assert rows[0]["vwap"] == 99.0
    assert rows[0]["price_vs_vwap_pct"] > 0
    assert rows[0]["pcr_view"] == "SUPPORTIVE"
    assert rows[0]["underlying_rsi"] == 62.4
    assert rows[0]["option_rsi"] == 56.0
    assert rows[0]["authority"] == "OBSERVATIONAL_ONLY"


def test_empty_store_returns_no_candidates(tmp_path):
    assert read_latest_trade_candidates(tmp_path / "missing.db") == []
