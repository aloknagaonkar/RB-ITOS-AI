from pathlib import Path


def test_carry_forward_interpretation_uses_text_only_value_column():
    page = Path(__file__).resolve().parents[1] / "ui" / "pages" / "previous_session_context.py"
    text = page.read_text(encoding="utf-8")

    assert '"Closing PCR", "Value": f"{context.closing_pcr:.4f}"' in text
    assert '"Closing Strength", "Value": str(context.closing_bias)' in text
    assert '"Carry-Forward", "Value": str(context.carry_forward_bias)' in text
    assert "Mixing a float PCR value with text" in text
