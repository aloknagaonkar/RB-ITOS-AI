from market_lab.hilega_directional_parity_v1 import (
    _decision_projection,
    _trade_projection,
    _compare_maps,
)


def decision(ts, *, owner="NONE"):
    return {
        "stage": "DIRECTIONAL_DECISION",
        "status": "PROCESSED",
        "checkpoint": ts,
        "payload": {
            "strategy_id":
                "HILEGA_DIRECTIONAL_SHADOW_V1",
            "bar_timestamp": ts,
            "trade_owner_before": owner,
            "trade_owner_after": owner,
            "bullish_state": "PATH1_IDLE",
            "bearish_state": "BEARISH_PATH1_IDLE",
            "bullish_armed": False,
            "bearish_armed": False,
            "accepted_events": [],
            "suppressed_events": [],
            "note": None,
        },
    }


def leg(i, *, entry=100.0, exit_=110.0):
    return {
        "relation_to_atm": i,
        "strike": 23000 + (i * 50),
        "side": "CE",
        "instrument_key": f"CE{i}",
        "entry_timestamp":
            "2026-09-25T10:05:00+05:30",
        "entry_open": entry,
        "latest_completed_minute":
            "2026-09-25T10:25:00+05:30",
        "latest_close": exit_,
        "current_points": exit_ - entry,
        "current_return_pct": 10.0,
        "mfe_points": 15.0,
        "mfe_pct": 15.0,
        "mae_points": -2.0,
        "mae_pct": -2.0,
        "exit_timestamp":
            "2026-09-25T10:30:00+05:30",
        "exit_open": exit_,
        "realized_points": exit_ - entry,
        "realized_return_pct": 10.0,
    }


def test_directional_decision_projection_is_semantic():
    ts = "2026-09-25T10:00:00+05:30"

    out = _decision_projection([
        decision(ts)
    ])

    assert list(out) == [ts]
    assert out[ts]["trade_owner_after"] == "NONE"


def test_trade_projection_treats_recovery_as_authoritative_closed():
    signal = "2026-09-25T10:00:00+05:30"

    incomplete = {
        "stage": "BULLISH_OPTION_SHADOW_START",
        "status": "INCOMPLETE",
        "payload": {
            "signal_bar": signal,
            "signal_boundary":
                "2026-09-25T10:05:00+05:30",
            "signal_spot": 23010.0,
            "expiry": "2026-09-29",
            "atm": 23000.0,
            "status": "INCOMPLETE",
            "issue": "MISSING_ENTRY_MINUTE",
            "legs": [],
        },
    }

    recovered = {
        "stage": "BULLISH_OPTION_SHADOW_RECOVERY",
        "status": "PASS",
        "payload": {
            "signal_bar": signal,
            "signal_boundary":
                "2026-09-25T10:05:00+05:30",
            "signal_spot": 23010.0,
            "expiry": "2026-09-29",
            "atm": 23000.0,
            "status": "CLOSED",
            "issue": None,
            "exit_reason":
                "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
            "legs": [
                leg(i)
                for i in (-2, -1, 0, 1, 2)
            ],
        },
    }

    out = _trade_projection([
        incomplete,
        recovered,
    ])

    trade = out[("BULLISH", signal)]

    assert trade["status"] == "CLOSED"
    assert len(trade["legs"]) == 5
    assert all(
        x["exit_open"] == 110.0
        for x in trade["legs"]
    )


def test_transient_history_does_not_change_final_trade_parity():
    signal = "2026-09-25T10:00:00+05:30"

    final = {
        "stage": "BULLISH_OPTION_SHADOW_RECOVERY",
        "status": "PASS",
        "payload": {
            "signal_bar": signal,
            "signal_boundary":
                "2026-09-25T10:05:00+05:30",
            "signal_spot": 23010.0,
            "expiry": "2026-09-29",
            "atm": 23000.0,
            "status": "CLOSED",
            "issue": None,
            "exit_reason":
                "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
            "legs": [
                leg(i)
                for i in (-2, -1, 0, 1, 2)
            ],
        },
    }

    historical = _trade_projection([final])

    live = _trade_projection([
        {
            "stage":
                "BULLISH_OPTION_SHADOW_START",
            "status": "INCOMPLETE",
            "payload": {
                "signal_bar": signal,
                "status": "INCOMPLETE",
                "issue": "MISSING_ENTRY_MINUTE",
                "legs": [],
            },
        },
        final,
    ])

    cmp = _compare_maps(
        historical,
        live,
        tolerance=1e-6,
    )

    assert cmp["mismatches"] == []
    assert cmp["missing_in_live"] == []
    assert cmp["missing_in_historical"] == []


def test_directional_historical_parity_replay_uses_production_coordinator(
    tmp_path,
):
    from datetime import date

    from test_hilega_milega_functional_parity_replay_v1 import (
        Gateway,
    )
    from market_lab.hilega_directional_parity_v1 import (
        HilegaDirectionalHistoricalFunctionalParityReplayV1,
    )

    d = date(2026, 9, 23)

    replay = HilegaDirectionalHistoricalFunctionalParityReplayV1(
        gateway=Gateway(),
        session_date=d,
        option_expiry=d,
        output_root=tmp_path,
        warmup_calendar_days=0,
        acquisition_today=d,
    )

    result = replay.run()

    assert result["audit_chain_ok"] is True
    assert result["processed_5m_bars"] > 0
    assert result["directional_decisions"] > 0
    assert result["observation_only"] is True
    assert result["execution_enabled"] is False
    assert result["paper_order_enabled"] is False

    rows = replay.coordinator.step_audit.read_all()

    stages = {
        row.get("stage")
        for row in rows
    }

    assert "DIRECTIONAL_DECISION" in stages


def test_directional_replay_audit_compares_identically_end_to_end(
    tmp_path,
):
    from datetime import date

    from test_hilega_milega_functional_parity_replay_v1 import (
        Gateway,
    )
    from market_lab.hilega_directional_parity_v1 import (
        HilegaDirectionalHistoricalFunctionalParityReplayV1,
        compare_directional_audits,
    )

    d = date(2026, 9, 23)

    root = tmp_path / "replay"

    replay = HilegaDirectionalHistoricalFunctionalParityReplayV1(
        gateway=Gateway(),
        session_date=d,
        option_expiry=d,
        output_root=root,
        warmup_calendar_days=0,
        acquisition_today=d,
    )

    run = replay.run()

    audit = root / "step-audit.jsonl"

    result = compare_directional_audits(
        historical_path=audit,
        live_path=audit,
        session_date=d.isoformat(),
    )

    assert run["audit_chain_ok"] is True
    assert result["status"] == "PASS"

    assert (
        result["directional_decisions"]["compared_events"]
        > 0
    )

    assert (
        result["directional_decisions"]["mismatches"]
        == []
    )

    assert (
        result["directional_decisions"]["missing_in_live"]
        == []
    )

    assert (
        result["directional_decisions"]["missing_in_historical"]
        == []
    )


def test_parity_canonicalizes_recovery_exit_reason_aliases():
    from market_lab.hilega_directional_parity_v1 import (
        TRADE_FIELDS,
        _canonical_exit_reason,
    )

    assert "signal_spot" not in TRADE_FIELDS

    assert (
        _canonical_exit_reason(
            "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"
        )
        == "RSI_CROSS_BELOW_WMA21"
    )

    assert (
        _canonical_exit_reason(
            "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21"
        )
        == "RSI_CROSS_ABOVE_WMA21"
    )

    assert (
        _canonical_exit_reason("SESSION_CUTOFF_EXIT_1455_OPEN")
        == "SESSION_CUTOFF_EXIT_1455_OPEN"
    )
