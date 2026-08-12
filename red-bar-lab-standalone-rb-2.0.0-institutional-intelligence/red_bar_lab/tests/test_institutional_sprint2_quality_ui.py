from pathlib import Path


def test_institutional_intelligence_exposes_contract_quality_as_advisory_only():
    page = Path(__file__).resolve().parents[1] / "ui" / "pages" / "institutional_intelligence.py"
    text = page.read_text(encoding="utf-8")

    assert "Contract Quality Weighting" in text
    assert "Contracts Assessed" in text
    assert "Qualified" in text
    assert "Inferred ATM" in text
    assert "raw velocity remains unchanged" in text.lower()
    assert "execution impact remains NONE" in text
