from market_lab.hilega_milega_audit_report_v1 import build_audit_index


def _strategy(checkpoint, state_after, events=None):
    return [
        {
            "checkpoint": checkpoint,
            "event_time": checkpoint,
            "stage": "STRATEGY_DECISION",
            "status": "EVALUATED",
            "payload": {
                "strategy_id": "HILEGA_MILEGA_BULLISH_SHADOW_V1",
                "strategy_version": "1.0.0",
                "state_before": state_after,
                "bar_close": 100.0,
            },
        },
        {
            "checkpoint": checkpoint,
            "event_time": checkpoint,
            "stage": "STRATEGY_DECISION_RESULT",
            "status": "COMPLETE",
            "payload": {
                "strategy_id": "HILEGA_MILEGA_BULLISH_SHADOW_V1",
                "strategy_version": "1.0.0",
                "state_after": state_after,
                "events_emitted": events or [],
            },
        },
    ]


def test_orphan_signal_bar_is_projected_as_reconstructed_entry():
    rows = []
    rows += _strategy("2026-09-24T09:55:00+05:30", "PATH1_ARMED", ["PATH1_ARMED_RSI_CROSS_EMA3_UP"])
    rows.append({
        "checkpoint": None,
        "event_time": "2026-09-24T10:06:30+05:30",
        "stage": "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY",
        "status": "ACTIVE",
        "payload": {
            "status": "ACTIVE",
            "signal_bar": "2026-09-24T10:00:00+05:30",
            "signal_spot": 23235.65,
            "source": "PATH1_ROUTE_B_STRUCTURAL",
            "strategy_id": "HILEGA_MILEGA_BULLISH_SHADOW_V1",
            "strategy_version": "1.0.0",
            "legs": [],
        },
    })
    rows += _strategy("2026-09-24T10:05:00+05:30", "BULLISH_ACTIVE")

    reports = build_audit_index(rows, mode="LIVE_SHADOW", chain_ok=True)
    by_cp = {r["checkpoint"]: r for r in reports}

    recovered = by_cp["2026-09-24T10:00:00+05:30"]
    assert recovered["projection"]["kind"] == "RECONSTRUCTED_ENTRY"
    assert recovered["strategy"]["state_after"] == "BULLISH_ACTIVE"
    assert recovered["strategy"]["selected_route"] == "ROUTE_B"
    assert recovered["strategy"]["events_emitted"] == ["ENTRY_RECONSTRUCTED_FROM_OPTION_LIFECYCLE"]
    assert recovered["transitions"][0]["event_type"] == "ENTRY_RECONSTRUCTED_FROM_OPTION_LIFECYCLE"
    assert recovered["transitions"][0]["source"] == "PATH1_ROUTE_B_STRUCTURAL"
    assert recovered["transitions"][0]["price"] == 23235.65
    assert recovered["bar"]["close"] is None
    assert recovered["indicators"]["rsi9"] is None


def test_real_strategy_checkpoint_prevents_reconstructed_duplicate():
    cp = "2026-09-24T10:00:00+05:30"
    rows = _strategy(cp, "BULLISH_ACTIVE", ["ENTRY_PATH1_ROUTE_B_STRUCTURAL"])
    rows.append({
        "checkpoint": None,
        "event_time": "2026-09-24T10:06:30+05:30",
        "stage": "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY",
        "status": "ACTIVE",
        "payload": {
            "status": "ACTIVE",
            "signal_bar": cp,
            "signal_spot": 23235.65,
            "source": "PATH1_ROUTE_B_STRUCTURAL",
        },
    })

    reports = build_audit_index(rows, mode="LIVE_SHADOW")
    matching = [r for r in reports if r["checkpoint"] == cp]
    assert len(matching) == 1
    assert matching[0].get("projection") is None
