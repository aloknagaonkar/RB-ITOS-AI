from red_bar_lab.services.operations_readiness_gate import build_operations_readiness_gate


def _signal(signal_id: str):
    return {
        "signal_id": signal_id,
        "confirmation_timestamp": "2026-08-21T06:10:00+00:00",
    }


def _reference(signal_id: str):
    return {
        "signal_id": signal_id,
        "reference_type": "NEXT_RED_CANDLE",
        "reference_timestamp": "2026-08-21T06:09:00+00:00",
        "reference_high": 100.0,
        "reference_low": 98.0,
        "reference_midpoint": 99.0,
        "data_quality": "VALID",
    }


def test_gate_uses_exact_signal_intersections_and_reference_readiness():
    result = build_operations_readiness_gate(
        confirmed_signals=[_signal("RBV2-1"), _signal("RBV2-2")],
        references_by_signal={"RBV2-1": _reference("RBV2-1")},
        market_outcomes=[
            {"signal_id": "RBV2-1", "status": "READY"},
            {"signal_id": "RBV2-2", "status": "READY"},
        ],
        volume_outcomes=[{"signal_id": "RBV2-1", "status": "READY"}],
        option_outcomes=[
            {"signal_id": "RBV2-1", "status": "READY"},
            {"signal_id": "RBV2-2", "status": "READY"},
        ],
    )

    assert result["core_signal_ids"] == ("RBV2-1",)
    assert result["hybrid_signal_ids"] == ("RBV2-1",)
    assert result["reference_ready_ids"] == ("RBV2-1",)
    assert result["readiness_domains"].red_bar_v2_readiness.status == "BLOCKED"
    assert result["readiness_domains"].independent_strategy_readiness.status == "READY"

    rows = {row["signal_id"]: row for row in result["drilldown"]}
    assert rows["RBV2-1"]["core_eligible"] is True
    assert rows["RBV2-1"]["hybrid_eligible"] is True
    assert rows["RBV2-2"]["reference_status"] == "MISSING"
    assert rows["RBV2-2"]["main_reason"] == "REFERENCE_NOT_FOUND"


def test_market_data_blocker_is_separate_from_strategy_and_execution_domains():
    result = build_operations_readiness_gate(
        confirmed_signals=[_signal("RBV2-1")],
        references_by_signal={"RBV2-1": _reference("RBV2-1")},
        market_outcomes=[{"signal_id": "RBV2-1", "status": "READY"}],
        volume_outcomes=[{"signal_id": "RBV2-1", "status": "READY"}],
        option_outcomes=[{"signal_id": "RBV2-1", "status": "READY"}],
        market_data_blockers=["OPTION_COLLECTOR_STALE"],
    )

    domains = result["readiness_domains"]
    assert domains.market_data_readiness.status == "BLOCKED"
    assert domains.independent_strategy_readiness.status == "READY"
    assert domains.red_bar_v2_readiness.status == "READY"
    assert domains.execution_readiness.status == "BLOCKED"
    assert result["authority"] == "OBSERVATIONAL_ONLY"


def test_failed_stage_reason_is_visible_in_signal_drilldown():
    result = build_operations_readiness_gate(
        confirmed_signals=[_signal("RBV2-1")],
        references_by_signal={"RBV2-1": _reference("RBV2-1")},
        market_outcomes=[
            {
                "signal_id": "RBV2-1",
                "status": "MISSING",
                "reason_code": "CURRENT_DAY_CANDLES_UNAVAILABLE",
            }
        ],
        volume_outcomes=[
            {
                "signal_id": "RBV2-1",
                "status": "MISSING",
                "reason_code": "CURRENT_DAY_CANDLES_UNAVAILABLE",
            }
        ],
        option_outcomes=[{"signal_id": "RBV2-1", "status": "READY"}],
    )

    row = result["drilldown"][0]
    assert row["core_eligible"] is False
    assert row["hybrid_eligible"] is False
    assert row["main_reason"] == "CURRENT_DAY_CANDLES_UNAVAILABLE"
    assert row["all_reasons"] == (
        "CURRENT_DAY_CANDLES_UNAVAILABLE",
        "CURRENT_DAY_CANDLES_UNAVAILABLE",
    )
