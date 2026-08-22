from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "pages" / "market_readiness.py"


def test_trade_evidence_page_exposes_monitor_safety_state():
    source = PAGE.read_text(encoding="utf-8")

    assert "Paper monitor safety state" in source
    assert "POSITION_MANAGEMENT_ONLY" in source
    assert "New paper entries are suspended" in source
    assert "confirmed reversal exits remain active" in source
    assert "read_paper_monitor_status" in source
