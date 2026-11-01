from scripts import analyze_hilega_wma_gap_daily_failures as m


TOP = {"BULLISH": 70.0, "BEARISH": 75.0}


def trade(**changes):
    row = {
        "trade_id": "t1",
        "session_date": "2026-10-01",
        "evidence_block": "OBSERVED_FORWARD",
        "direction": "BULLISH",
        "canonical_points": "-20",
        "first_touch_points": "",
        "candidate_points": "",
        "candidate_delta_vs_canonical": "",
        "candidate_decision": "NO_ENTRY",
        "mfe_points": "5",
        "mae_points": "-22",
        "canonical_reached_plus20": "False",
    }
    row.update(changes)
    return m.enrich_trade(row, TOP)


def test_denied_loss_is_saved_not_realized_loss():
    row = trade()
    assert row["saved_denied_loss_points"] == 20
    assert row["accepted_candidate_loss_points"] == 0


def test_denied_winner_is_opportunity_loss():
    row = trade(canonical_points="15", mfe_points="30")
    assert row["denied_winner_opportunity_points"] == 15
    assert row["canonical_reached_plus20"] is False


def test_accepted_loss_and_delay_are_separate_diagnostics():
    row = trade(
        canonical_points="-5",
        candidate_points="-12",
        candidate_delta_vs_canonical="-7",
        candidate_decision="ENTRY",
    )
    assert row["accepted_candidate_loss_points"] == 12
    assert row["adverse_entry_delay_cost_points"] == 7


def test_daily_lost_vs_canonical_is_policy_level_difference():
    rows = [
        trade(canonical_points="10", candidate_decision="NO_ENTRY"),
        trade(
            trade_id="t2",
            canonical_points="-5",
            candidate_points="-8",
            candidate_delta_vs_canonical="-3",
            candidate_decision="ENTRY",
        ),
    ]
    result = m.summarize(rows, "ALL")
    assert result["canonical_points"] == 5
    assert result["candidate_points"] == -8
    assert result["lost_vs_canonical_points"] == 13


def test_top_decile_denial_is_counted():
    row = trade(mfe_points="80")
    result = m.summarize([row], "BULLISH")
    assert result["top_decile_moves_destroyed"] == 1

