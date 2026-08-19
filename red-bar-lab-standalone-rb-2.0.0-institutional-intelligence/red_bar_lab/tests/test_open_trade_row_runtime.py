from __future__ import annotations

from types import SimpleNamespace

from red_bar_lab.ui.open_trade_row_runtime import (
    classify_exit_level,
    enrich_open_trade_rows,
    install,
)


def _row(current=112.0):
    return {
        "Order": "PAPER-1",
        "Entry": 100.0,
        "Current": current,
        "Stop": 85.0,
        "Target": 120.0,
        "Target 2": 135.0,
        "Status": "OPEN",
    }


def test_enriches_existing_open_trade_row():
    row = enrich_open_trade_rows([_row()])[0]

    assert row["Move %"] == 12.0
    assert row["Current Exit Level"] == "PROFIT ZONE"
    assert row["Target 1"] == 120.0
    assert row["Target 2"] == 135.0
    assert row["Exit Mode"] == "ACTIVE POLICY"
    assert "Target" not in row


def test_classifies_exit_levels():
    assert classify_exit_level(_row(82.0)) == "AT / BELOW STOP"
    assert classify_exit_level(_row(90.0)) == "BETWEEN ENTRY AND STOP"
    assert classify_exit_level(_row(120.0)) == "TARGET 1 REACHED"
    assert classify_exit_level(_row(138.0)) == "TARGET 2 REACHED"


def test_installs_only_for_paper_trading_module():
    module = SimpleNamespace(
        __name__="red_bar_lab.ui.pages.paper_trading",
        _arrow_safe_rows=lambda rows: list(rows),
    )

    install(module)
    result = module._arrow_safe_rows([_row()])

    assert result[0]["Current Exit Level"] == "PROFIT ZONE"
    assert module._open_trade_row_runtime_installed is True
