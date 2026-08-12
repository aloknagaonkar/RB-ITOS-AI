from pathlib import Path
from types import SimpleNamespace

from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine


def _row(strike, side, bias, activity, behaviour, confidence):
    return SimpleNamespace(
        strike=strike,
        option_type=side,
        directional_bias=bias,
        institutional_activity=activity,
        behaviour=behaviour,
        confidence_pct=confidence,
    )


def test_strength_explanation_preserves_existing_aggregate_and_exposes_contributors():
    rows = (
        _row(24450, "CE", "BULLISH", "CALL_BUYING", "LONG_BUILDUP", 80),
        _row(24500, "PE", "BEARISH", "PUT_BUYING", "LONG_BUILDUP", 60),
    )
    result = BuySellStrengthEngine.evaluate(rows)

    assert result.buying_strength_pct == 57.14
    assert result.selling_strength_pct == 42.86
    assert result.net_strength == 14.29
    assert len(result.contributions) == 2
    assert result.contributions[0].activity == "CALL_BUYING"
    assert result.contributions[0].directional_bias == "BULLISH"
    assert result.contributions[0].weighted_score == 80
    assert result.contributions[1].activity == "PUT_BUYING"
    assert result.contributions[1].directional_bias == "BEARISH"


def test_institutional_ui_exposes_read_only_strength_explanation():
    page = Path(__file__).resolve().parents[1] / "ui" / "pages" / "institutional_intelligence.py"
    text = page.read_text(encoding="utf-8")

    assert "Buying / Selling Strength Explanation" in text
    assert "Top Buying Contributors" in text
    assert "Top Selling Contributors" in text
    assert "Weighted Contribution" in text
    assert "does not change the calculation or execution" in text
