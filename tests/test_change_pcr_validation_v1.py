import json
from pathlib import Path

import pytest

from backend.market_lab.change_pcr_validation_v1 import (
    change_pcr,
    change_pcr_mechanics,
    delta_pattern,
    existing_horizon_state,
    build_rows,
)


def test_change_pcr_basic_and_undefined():
    assert change_pcr(10.0, 20.0) == 2.0
    assert change_pcr(10.0, -5.0) == -0.5
    assert change_pcr(-10.0, 20.0) == -2.0
    assert change_pcr(-10.0, -20.0) == 2.0
    assert change_pcr(0.0, 20.0) is None
    assert change_pcr(None, 20.0) is None
    assert change_pcr(10.0, None) is None


def test_delta_patterns():
    assert delta_pattern(1, 2) == "CE+/PE+"
    assert delta_pattern(1, -2) == "CE+/PE-"
    assert delta_pattern(-1, 2) == "CE-/PE+"
    assert delta_pattern(-1, -2) == "CE-/PE-"
    assert delta_pattern(0, 2) == "CE0/PE+"
    assert delta_pattern(None, 2) == "NA"


def test_change_pcr_mechanics():
    assert change_pcr_mechanics(10, 20, 2.0) == "BOTH_BUILD_PE_DOMINANT"
    assert change_pcr_mechanics(20, 10, 0.5) == "BOTH_BUILD_CE_DOMINANT"
    assert change_pcr_mechanics(10, -5, -0.5) == "CE_BUILD_PE_UNWIND"
    assert change_pcr_mechanics(-10, 5, -0.5) == "CE_UNWIND_PE_BUILD"
    assert change_pcr_mechanics(-10, -20, 2.0) == "BOTH_UNWIND_PE_DOMINANT"
    assert change_pcr_mechanics(-20, -10, 0.5) == "BOTH_UNWIND_CE_DOMINANT"


def test_existing_state_does_not_use_change_pcr():
    assert existing_horizon_state(1, 0.1) == "BULLISH"
    assert existing_horizon_state(-1, -0.1) == "BEARISH"
    assert existing_horizon_state(1, -0.1) == "MIXED"
    assert existing_horizon_state(None, 0.1) == "NA"


def test_build_rows_from_frozen_audit(tmp_path: Path):
    payload = {
        "status": "PASS",
        "session_date": "2026-08-25",
        "rows": [{
            "timestamp": "2026-08-25T09:40:00+05:30",
            "spot": 24169.25,
            "moving_atm": 24150.0,
            "ce_delta_5m": 9055540.0,
            "pe_delta_5m": 2252250.0,
            "imbalance_5m": -6803290.0,
            "pcr_change_5m": -0.0538388597461088,
            "ce_delta_10m": 16496090.0,
            "pe_delta_10m": 10934170.0,
            "imbalance_10m": -5561920.0,
            "pcr_change_10m": -0.050366377878500845,
            "ce_delta_15m": 21050250.0,
            "pe_delta_15m": 19974890.0,
            "imbalance_15m": -1075360.0,
            "pcr_change_15m": -0.01781811568060121,
            "futures_oi_direction": "BEARISH",
            "futures_oi_status": "LONG_UNWINDING",
            "vwap_side": "ABOVE",
            "session_pcr_change_0920_to_now": 0.04730799409351094,
            "evaluation_label": "BEARISH",
            "fallback_used": True,
        }],
    }
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(payload))

    rows, sessions = build_rows([path])
    assert sessions == ["2026-08-25"]
    assert len(rows) == 3

    r5 = rows[0]
    assert r5["horizon"] == "5m"
    assert r5["delta_pattern"] == "CE+/PE+"
    assert r5["change_pcr"] == pytest.approx(2252250.0 / 9055540.0)
    assert r5["change_pcr_mechanics"] == "BOTH_BUILD_CE_DOMINANT"
    assert r5["existing_horizon_state"] == "BEARISH"
