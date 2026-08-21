from red_bar_lab.services.readiness_domains import build_readiness_domains
from red_bar_lab.ui.operations_readiness_view import (
    build_operations_readiness_view_model,
)


def _gate():
    return {
        "policy_version": "operations-readiness-gate-v2",
        "authority": "OBSERVATIONAL_ONLY",
        "confirmed_signal_ids": ("RBV2-1", "RBV2-2"),
        "reference_ready_ids": ("RBV2-1",),
        "market_ready_ids": ("RBV2-1", "RBV2-2"),
        "volume_ready_ids": ("RBV2-1",),
        "option_ready_ids": ("RBV2-1", "RBV2-2"),
        "core_signal_ids": ("RBV2-1",),
        "hybrid_signal_ids": ("RBV2-1",),
        "readiness_domains": {
            "market_data_readiness": {"status": "READY", "reasons": ()},
            "independent_strategy_readiness": {"status": "READY", "reasons": ()},
            "red_bar_v2_readiness": {
                "status": "BLOCKED",
                "reasons": ("RBV2-2:REFERENCE_NOT_FOUND",),
            },
            "execution_readiness": {
                "status": "BLOCKED",
                "reasons": ("EXECUTION_POLICY_NOT_APPROVED",),
            },
        },
        "drilldown": (
            {
                "signal_id": "RBV2-1",
                "confirmation_timestamp": "2026-08-21T06:05:00+00:00",
                "reference_type": "NEXT_RED_CANDLE",
                "reference_status": "READY",
                "reference_timestamp": "2026-08-21T05:45:00+00:00",
                "market_status": "READY",
                "market_source": "LIVE_PERSISTED",
                "market_latest_timestamp": "2026-08-21T10:04:00+05:30",
                "market_row_count": 49,
                "market_fallback_used": False,
                "market_no_lookahead_passed": True,
                "volume_status": "READY",
                "volume_source": "HISTORICAL_REPOSITORY",
                "volume_latest_timestamp": "2026-08-21T10:04:00+05:30",
                "volume_row_count": 49,
                "volume_fallback_used": True,
                "volume_no_lookahead_passed": True,
                "option_status": "READY",
                "core_eligible": True,
                "hybrid_eligible": True,
                "main_reason": None,
                "all_reasons": (),
            },
            {
                "signal_id": "RBV2-2",
                "confirmation_timestamp": "2026-08-21T06:10:00+00:00",
                "reference_type": "NEXT_RED_CANDLE",
                "reference_status": "MISSING",
                "reference_timestamp": None,
                "market_status": "READY",
                "volume_status": "MISSING",
                "option_status": "READY",
                "core_eligible": False,
                "hybrid_eligible": False,
                "main_reason": "REFERENCE_NOT_FOUND",
                "all_reasons": (
                    "REFERENCE_NOT_FOUND",
                    "VOLUME_CONTEXT_MISSING",
                ),
            },
        ),
    }


def test_view_model_uses_exact_signal_membership_counts():
    view = build_operations_readiness_view_model(_gate())
    assert view["confirmed_count"] == 2
    assert view["stages"]["market"]["ready_count"] == 2
    assert view["stages"]["volume"]["ready_count"] == 1
    assert view["stages"]["core"]["ready_count"] == 1
    assert view["stages"]["hybrid"]["ready_count"] == 1
    assert view["stages"]["core"]["status"] == "PARTIAL"


def test_view_model_keeps_readiness_domains_separate():
    view = build_operations_readiness_view_model(_gate())
    assert view["domains"]["market_data"]["status"] == "READY"
    assert view["domains"]["independent_strategy"]["status"] == "READY"
    assert view["domains"]["red_bar_v2"]["status"] == "BLOCKED"
    assert view["domains"]["red_bar_v2"]["primary_reason"] == "RBV2-2:REFERENCE_NOT_FOUND"
    assert view["domains"]["execution"]["status"] == "BLOCKED"


def test_view_model_accepts_typed_readiness_domains():
    gate = _gate()
    gate["readiness_domains"] = build_readiness_domains(
        red_bar_v2_reasons=("RBV2-2:REFERENCE_NOT_FOUND",),
        red_bar_v2_advisories=("REFERENCE_COVERAGE_PARTIAL",),
        execution_reasons=("EXECUTION_POLICY_NOT_APPROVED",),
    )
    view = build_operations_readiness_view_model(gate)
    assert view["domains"]["market_data"]["status"] == "READY"
    assert view["domains"]["red_bar_v2"]["blocking_reasons"] == (
        "RBV2-2:REFERENCE_NOT_FOUND",
    )
    assert view["domains"]["red_bar_v2"]["advisory_reasons"] == (
        "REFERENCE_COVERAGE_PARTIAL",
    )
    assert view["domains"]["execution"]["primary_reason"] == "EXECUTION_POLICY_NOT_APPROVED"


def test_view_model_formats_per_signal_drilldown():
    view = build_operations_readiness_view_model(_gate())
    rows = list(view["drilldown"])
    assert rows[0]["Signal"] == "RBV2-1"
    assert rows[0]["CORE"] == "YES"
    assert rows[0]["HYBRID"] == "YES"
    assert rows[1]["Reference"] == "MISSING"
    assert rows[1]["CORE"] == "NO"
    assert rows[1]["Primary reason"] == "REFERENCE_NOT_FOUND"
    assert "VOLUME_CONTEXT_MISSING" in rows[1]["All reasons"]


def test_view_model_formats_candle_source_diagnostics():
    rows = list(build_operations_readiness_view_model(_gate())["drilldown"])
    first = rows[0]
    assert first["Market source"] == "LIVE_PERSISTED"
    assert first["Market rows"] == 49
    assert first["Market fallback"] == "NO"
    assert first["Market no-lookahead"] == "YES"
    assert first["Volume source"] == "HISTORICAL_REPOSITORY"
    assert first["Volume fallback"] == "YES"
    assert first["Volume latest candle"] == "2026-08-21T10:04:00+05:30"


def test_empty_gate_is_waiting_and_observational():
    view = build_operations_readiness_view_model({})
    assert view["authority"] == "OBSERVATIONAL_ONLY"
    assert view["confirmed_count"] == 0
    assert view["stages"]["reference"]["status"] == "WAITING"
    assert view["drilldown"] == ()
