from pathlib import Path
from datetime import datetime, timezone

from red_bar_lab.services.market_direction_validation import (
    build_market_direction_validation,
)
from red_bar_lab.ui.market_direction_validation_panel import _source_rows


def _bundle(direction: str) -> dict[str, object]:
    return {
        "underlying_direction": direction,
        "observed_direction": direction,
        "acceptance_state": "HOLD_CONFIRMED",
        "early_1m_direction": direction,
        "early_1m_state": f"{direction}_BREAK",
        "evidence_readiness": "READY",
        "option_direction": direction,
        "futures_vwap_direction": direction,
    }


def _pcr(direction: str) -> dict[str, object]:
    positive = direction == "BULLISH"
    return {
        "quality": {"state": "READY"},
        "current_panel": {
            "aggregate": {
                "pcr": 1.35 if positive else 0.62,
                "absolute_change": 0.2 if positive else -0.2,
                "slope_per_minute": 0.02 if positive else -0.02,
                "persistence_state": "PERSISTENT",
                "consecutive_count": 4,
                "direction_evidence": {"direction": direction},
            }
        },
    }


def _option_rows(direction: str) -> list[dict[str, object]]:
    if direction == "BULLISH":
        return [
            {"strike": 24200, "option_type": "CE", "current_price": 90, "vwap": 82, "price_vs_vwap_pct": 9.8, "premium_change_from_previous_refresh_pct": 5.0, "oi_change_from_previous_refresh": 100, "volume_change_from_previous_refresh_pct": 8.0},
            {"strike": 24200, "option_type": "PE", "current_price": 50, "vwap": 60, "price_vs_vwap_pct": -16.7, "premium_change_from_previous_refresh_pct": -4.0, "oi_change_from_previous_refresh": 120, "volume_change_from_previous_refresh_pct": 7.0},
        ]
    return [
        {"strike": 24200, "option_type": "CE", "current_price": 50, "vwap": 60, "price_vs_vwap_pct": -16.7, "premium_change_from_previous_refresh_pct": -4.0, "oi_change_from_previous_refresh": 120, "volume_change_from_previous_refresh_pct": 7.0},
        {"strike": 24200, "option_type": "PE", "current_price": 90, "vwap": 82, "price_vs_vwap_pct": 9.8, "premium_change_from_previous_refresh_pct": 5.0, "oi_change_from_previous_refresh": 100, "volume_change_from_previous_refresh_pct": 8.0},
    ]


def _futures(direction: str) -> dict[str, object]:
    return {
        "positioning_state": "LONG_BUILDUP" if direction == "BULLISH" else "SHORT_BUILDUP",
        "futures_vwap_acceptance": "ABOVE_VWAP" if direction == "BULLISH" else "BELOW_VWAP",
        "relative_volume": 1.4,
        "oi_change_pct": 4.0,
        "readiness_status": "READY",
    }


def test_aligned_bullish_evidence_is_observational_bullish() -> None:
    result = build_market_direction_validation(
        authoritative_bundle=_bundle("BULLISH"),
        option_rows=_option_rows("BULLISH"),
        futures_snapshot=_futures("BULLISH"),
        pcr_projection=_pcr("BULLISH"),
    )

    assert result.conclusion == "BULLISH"
    assert result.bullish_score == 100.0
    assert result.bearish_score == 0.0
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_aligned_bearish_evidence_is_observational_bearish() -> None:
    result = build_market_direction_validation(
        authoritative_bundle=_bundle("BEARISH"),
        option_rows=_option_rows("BEARISH"),
        futures_snapshot=_futures("BEARISH"),
        pcr_projection=_pcr("BEARISH"),
    )

    assert result.conclusion == "BEARISH"
    assert result.bearish_score == 100.0
    assert result.bullish_score == 0.0


def test_missing_sources_fail_closed_without_direction() -> None:
    result = build_market_direction_validation(
        authoritative_bundle=None,
        option_rows=[],
        futures_snapshot=None,
        pcr_projection=None,
    )

    assert result.conclusion == "UNAVAILABLE"
    assert result.quality == "INCOMPLETE"


def test_structure_disagreement_returns_conflict() -> None:
    result = build_market_direction_validation(
        authoritative_bundle=_bundle("BULLISH"),
        option_rows=_option_rows("BEARISH"),
        futures_snapshot=_futures("BEARISH"),
        pcr_projection=_pcr("BEARISH"),
    )

    assert result.conclusion == "CONFLICT"


def test_trade_evidence_registers_separate_validation_tab() -> None:
    source = Path("red_bar_lab/ui/pages/market_readiness.py").read_text(
        encoding="utf-8"
    )

    assert '"Market Trend Research"' in source
    assert '"Market Direction Validation"' in source
    assert source.index('"Market Trend Research"') < source.index(
        '"Market Direction Validation"'
    )
    assert "render_market_direction_validation_panel" in source


def test_validation_panel_declares_no_trading_authority() -> None:
    source = Path(
        "red_bar_lab/ui/market_direction_validation_panel.py"
    ).read_text(encoding="utf-8")

    assert '"signal_generated": False' in source
    assert '"canonical_bundle_created": False' in source
    assert '"opportunity_queued": False' in source
    assert '"paper_trade_created": False' in source
    assert "OBSERVATIONAL_ONLY" in source
    assert "MARKET_TREND_RESEARCH_UI_REFRESH_SECONDS" in source
    assert "@_fragment(run_every=" in source
    assert "requests" not in source
    assert "Upstox" not in source


def test_source_freshness_uses_separate_market_data_limits() -> None:
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
    rows = _source_rows(
        bundle={"underlying_timestamp": "2026-08-24T09:55:00+00:00"},
        option_rows=[{"observed_at": "2026-08-24T09:59:00+00:00"}],
        futures={"bar_close_timestamp": "2026-08-24T09:55:00+00:00"},
        projection={"source_timestamp": "2026-08-24T09:59:20+00:00"},
        now=now,
    )

    assert [row["Status"] for row in rows] == [
        "FRESH",
        "FRESH",
        "FRESH",
        "STALE",
    ]
