from red_bar_lab.ui.live_trade_card_validation import build_live_validation


def test_open_trade_validation_passes_with_fresh_complete_indicators():
    result = build_live_validation(
        {
            "status": "OPEN",
            "freshness": {"status": "FRESH"},
            "entry_snapshot_source": "ACTIVE_CAPTURE",
            "current_pcr": 1.22,
            "current_delta": -0.48,
            "current_option_vwap": 152.4,
            "current_option_rsi14": 61.7,
        },
        render_ms=84.0,
    )

    assert result["overall"] == "PASS"
    assert all(row["state"] == "PASS" for row in result["checks"])
    assert result["authority"] == "OBSERVATIONAL ONLY"


def test_open_trade_validation_reports_indicator_warmup_without_failure():
    result = build_live_validation(
        {
            "status": "OPEN",
            "freshness": {"status": "FRESH"},
            "entry_snapshot_source": "ACTIVE_CAPTURE",
            "current_pcr": 1.1,
            "current_delta": 0.43,
            "current_option_vwap": None,
            "current_option_rsi14": None,
        },
        render_ms=120.0,
    )

    assert result["overall"] == "WARMING_UP"
    states = {row["check"]: row["state"] for row in result["checks"]}
    assert states["CURRENT option VWAP"] == "WARMING_UP"
    assert states["CURRENT option RSI-14"] == "WARMING_UP"


def test_closed_trade_validation_checks_exit_lifecycle_and_performance():
    result = build_live_validation(
        {
            "status": "CLOSED",
            "freshness": {"status": "STALE"},
            "entry_snapshot_source": "ACTIVE_CAPTURE",
            "exit_snapshot_source": "EXACT_EXIT_QUOTE_WITH_ACTIVE_CONTEXT",
            "exit_data_quality": "PARTIAL_EXACT",
            "current_pcr": 1.35,
            "current_delta": -0.55,
            "current_option_vwap": 168.2,
            "current_option_rsi14": 69.1,
        },
        render_ms=810.0,
    )

    assert result["overall"] == "ATTENTION"
    states = {row["check"]: row["state"] for row in result["checks"]}
    assert states["Exit lifecycle"] == "PASS"
    assert states["Telemetry freshness"] == "WARN"
    assert states["Selected card render"] == "SLOW"
