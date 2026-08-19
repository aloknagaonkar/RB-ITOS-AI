from red_bar_lab.ui.open_trade_row_enrichment import (
    current_exit_level,
    enrich_open_trade_rows,
)


def _row(current):
    return {
        "Order": "PAPER-1",
        "Option": "NIFTY 24050 PE",
        "Entry": 100.0,
        "Current": current,
        "Stop": 85.0,
        "Target": 120.0,
        "Status": "OPEN",
    }


def test_current_exit_level_examples():
    assert current_exit_level(_row(82.0)) == "AT / BELOW STOP"
    assert current_exit_level(_row(90.0)) == "BETWEEN ENTRY AND STOP"
    assert current_exit_level(_row(105.0)) == "PROFIT ZONE"
    assert current_exit_level(_row(122.0)) == "TARGET 1 REACHED"


def test_enriches_existing_open_trade_row_in_place_shape():
    result = enrich_open_trade_rows([_row(112.0)])

    assert len(result) == 1
    assert result[0]["Move %"] == 12.0
    assert result[0]["Current Exit Level"] == "PROFIT ZONE"
    assert result[0]["Target 1"] == 120.0
    assert "Target" not in result[0]


def test_unrelated_table_is_unchanged():
    source = [{"Candidate": "NIFTY", "Score": 88.0}]
    assert enrich_open_trade_rows(source) == source
