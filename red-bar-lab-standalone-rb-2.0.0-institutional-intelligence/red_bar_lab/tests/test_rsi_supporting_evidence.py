from red_bar_lab.execution.directional_regime_native_signal import decide_native_signal


def _signal(
    signal_id: str,
    *,
    direction: str = "BULLISH",
    source: str,
    timestamp: str = "2026-08-14T09:31:00+05:30",
    **extra,
):
    return {
        "signal_id": signal_id,
        "direction": direction,
        "signal_source": source,
        "source": source,
        "confirmation_timestamp": timestamp,
        **extra,
    }


def test_red_bar_remains_executable_without_rsi_confirmation():
    red_bar = _signal("REF-1", source="REFERENCE_LEVEL")

    # RSI is absent. Existing Red Bar behaviour must remain unchanged; the
    # supporting-evidence adapter does not reject or modify the Red Bar row.
    assert red_bar["direction"] == "BULLISH"
    assert red_bar["signal_source"] == "REFERENCE_LEVEL"
    assert "RSI_EXTREME_REVERSAL_V1" not in red_bar.get("signal_sources", [])


def test_dri_remains_executable_without_rsi_confirmation():
    dri = _signal(
        "DRI-BND-1",
        source="DIRECTIONAL_REGIME_INTELLIGENCE",
        bundle_id="BND-1",
    )

    # RSI is optional supporting evidence, not a DRI entry gate.
    assert dri["direction"] == "BULLISH"
    assert dri["signal_source"] == "DIRECTIONAL_REGIME_INTELLIGENCE"
    assert "RSI_EXTREME_REVERSAL_V1" not in dri.get("signal_sources", [])


def test_same_direction_red_bar_and_rsi_merge_as_supporting_evidence():
    red_bar = _signal("REF-1", source="REFERENCE_LEVEL")
    rsi = _signal(
        "RSI-1",
        source="RSI_EXTREME_REVERSAL_V1",
        timestamp="2026-08-14T09:32:00+05:30",
        rsi_period=7,
        rsi_confirmation_value=24.0,
        strategy_stop_loss_pct=7.0,
    )

    decision = decide_native_signal(rsi, [red_bar])

    assert decision.action == "DUAL_SOURCE_ALIGNED"
    assert decision.native_signal is not None
    assert decision.native_signal["signal_id"] == "REF-1"
    assert decision.native_signal["source_count"] == 2
    assert decision.native_signal["merge_status"] == "DUAL_SOURCE_ALIGNED"
    assert set(decision.native_signal["signal_sources"]) == {
        "REFERENCE_LEVEL",
        "RSI_EXTREME_REVERSAL_V1",
    }
    assert decision.native_signal["rsi_signal_id"] == "RSI-1"


def test_same_direction_dri_and_rsi_merge_as_supporting_evidence():
    dri = _signal(
        "DRI-BND-1",
        source="DIRECTIONAL_REGIME_INTELLIGENCE",
        bundle_id="BND-1",
    )
    rsi = _signal(
        "RSI-1",
        source="RSI_EXTREME_REVERSAL_V1",
        timestamp="2026-08-14T09:32:00+05:30",
        rsi_period=7,
        rsi_confirmation_value=24.0,
        strategy_stop_loss_pct=7.0,
    )

    decision = decide_native_signal(rsi, [dri])

    assert decision.action == "DUAL_SOURCE_ALIGNED"
    assert decision.native_signal is not None
    assert decision.native_signal["signal_id"] == "DRI-BND-1"
    assert decision.native_signal["source_count"] == 2
    assert set(decision.native_signal["signal_sources"]) == {
        "DIRECTIONAL_REGIME_INTELLIGENCE",
        "RSI_EXTREME_REVERSAL_V1",
    }
    assert decision.native_signal["rsi_signal_id"] == "RSI-1"


def test_rsi_conflict_holds_existing_red_bar_bundle_instead_of_becoming_gate():
    red_bar = _signal("REF-1", direction="BEARISH", source="REFERENCE_LEVEL")
    rsi = _signal(
        "RSI-1",
        direction="BULLISH",
        source="RSI_EXTREME_REVERSAL_V1",
        timestamp="2026-08-14T09:32:00+05:30",
    )

    decision = decide_native_signal(rsi, [red_bar])

    assert decision.action == "SOURCE_CONFLICT"
    assert decision.native_signal is None
    assert decision.related_signal_id == "REF-1"


def test_same_direction_open_position_uses_rsi_as_reinforcement_only():
    rsi = _signal("RSI-1", source="RSI_EXTREME_REVERSAL_V1")
    open_order = {
        "signal_id": "REF-OPEN",
        "status": "OPEN",
        "direction": "BULLISH",
        "option_type": "CE",
    }

    decision = decide_native_signal(rsi, [], open_orders=[open_order])

    assert decision.action == "REINFORCEMENT_ONLY"
    assert decision.native_signal is None
    assert decision.related_signal_id == "REF-OPEN"
