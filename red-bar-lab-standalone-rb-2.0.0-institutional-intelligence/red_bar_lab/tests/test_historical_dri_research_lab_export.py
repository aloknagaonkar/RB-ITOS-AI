from pathlib import Path


def test_research_lab_contains_dri_diagnostic_export_columns():
    target = (
        Path(__file__).resolve().parents[1]
        / "ui"
        / "pages"
        / "research_lab.py"
    )
    text = target.read_text(encoding="utf-8")
    required = {
        '"Trailing Activated": row.trailing_activated',
        '"Trailing Exit": row.trailing_exit_price',
        '"Trailing Return %": row.trailing_return_pct',
        '"Reversal State": row.reversal_state',
        '"Reversal Reason": row.reversal_reason',
        '"Reversal EMA10 Slope":',
        '"Reversal EMA30 Slope":',
        '"Two Directional Closes":',
        '"Active Invalidation":',
        '"Invalidation Broken":',
        '"Reset/Rebreak Reason":',
    }
    for item in required:
        assert item in text
