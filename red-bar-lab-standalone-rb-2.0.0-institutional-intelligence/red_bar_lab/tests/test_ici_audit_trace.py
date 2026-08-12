from pathlib import Path

from red_bar_lab.intelligence.institutional_confidence import InstitutionalConfidence


def test_ici_audit_trace_reconstructs_existing_score():
    ici = InstitutionalConfidence(
        score=27.90,
        direction="BULLISH",
        quality="INSUFFICIENT",
        directional_edge=10.42,
        data_coverage_pct=79.3,
        components={
            "Directional Edge": 20.84,
            "OI Velocity": 65.63,
            "Premium Flow": 33.75,
            "Strike Rotation": 2.96,
            "Breadth": 19.52,
        },
    )

    assert len(ici.component_audit) == 5
    assert ici.component_audit[0]["Weight %"] == 35.0
    assert ici.component_audit[1]["Weight %"] == 20.0
    assert ici.component_audit[3]["Weight %"] == 10.0
    assert ici.component_audit[4]["Weight %"] == 15.0
    assert abs(ici.reconstructed_score - ici.score) <= 0.06
    assert "execution impact remains NONE" in ici.explanation


def test_institutional_ui_exposes_ici_audit_as_advisory_only():
    page = Path(__file__).resolve().parents[1] / "ui" / "pages" / "institutional_intelligence.py"
    text = page.read_text(encoding="utf-8")

    assert "ICI Explanation / Audit Trace" in text
    assert "Displayed ICI" in text
    assert "Reconstructed ICI" in text
    assert "Coverage Multiplier" in text
    assert "ICI audit parity PASS" in text
    assert "scoring and execution are unchanged" in text
