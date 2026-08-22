from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_PAGE = ROOT / "ui" / "pages" / "market_readiness.py"
LEGACY_PAGE = ROOT / "ui" / "pages" / "market_readiness_legacy.py"


def test_trade_evidence_page_exposes_authoritative_and_legacy_tabs():
    source = CURRENT_PAGE.read_text(encoding="utf-8")

    assert '"Authoritative Evidence"' in source
    assert '"Legacy Full Trade Evidence"' in source
    assert "render_legacy_page(" in source


def test_legacy_trade_evidence_sections_are_preserved():
    source = LEGACY_PAGE.read_text(encoding="utf-8")

    required_sections = (
        "Today's Spot & ATM ± 4 Option Participation",
        "CE / PE totals and change from prior refresh",
        "Independent Market Recommendation",
        "Best five independent trade candidates",
        "Red Bar V2 Recommendation",
        "Recommendation Alignment",
        "Market Readiness Detail",
        "Component readiness",
        "Shadow validation",
        "Historical readiness replay",
        "Latest snapshot",
        "Recent history",
    )
    for section in required_sections:
        assert section in source


def test_legacy_page_remains_observational_only():
    source = LEGACY_PAGE.read_text(encoding="utf-8")

    assert "OBSERVATIONAL_ONLY" in source
    assert "no execution authority" in source
    assert "open_long_option" not in source
    assert "insert_paper_execution_order" not in source
