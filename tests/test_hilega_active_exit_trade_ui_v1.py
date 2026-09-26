from pathlib import Path
from market_lab.hilega_milega_audit_report_v1 import _related_to_checkpoint

def test_underlying_runtime_processing_row_links_to_checkpoint():
    cp="2026-09-24T10:35:00+05:30"
    row={"checkpoint":None,"stage":"UNDERLYING_5M_BUILD","payload":{"bar_timestamp":cp}}
    assert _related_to_checkpoint(row,cp)

def test_trade_ui_sections_and_timing_contract():
    s=Path("frontend/src/hilegaMilegaShadow.tsx").read_text(encoding="utf-8")
    t=Path("frontend/src/hilegaDecisionTable.tsx").read_text(encoding="utf-8")
    assert "Shadow premium P&amp;L dashboard" not in s
    assert "CE entry / exit trade ledger" not in s
    assert "Active option shadow trade" in s
    assert "Exited option shadow trades" in s
    assert "activeTrades" in s and "exitedTrades" in s
    assert "candleTiming" in t
    assert "UNDERLYING_5M_BUILD" in t
    assert "BOOTSTRAP_RECOVERED_CHECKPOINT" in t
