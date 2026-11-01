from market_lab.hilega_directional_trade_dashboard_v1 import project_directional_shadow_dashboard


def _legs(side="PE", exit_=False):
    out = []
    for rel in (-2, -1, 0, 1, 2):
        strike = 23450 + rel * 50
        row = {
            "relation_to_atm": rel,
            "strike": strike,
            "side": side,
            "instrument_key": f"{side}{strike}",
            "entry_timestamp": "2026-09-24T10:35:00+05:30",
            "entry_open": 100 + rel * 5,
            "latest_completed_minute": "2026-09-24T10:44:00+05:30",
            "latest_close": 110 + rel * 5,
            "current_points": 10,
            "current_return_pct": 10,
            "mfe_points": 12,
            "mfe_pct": 12,
            "mae_points": -3,
            "mae_pct": -3,
            "exit_timestamp": "2026-09-24T10:45:00+05:30" if exit_ else None,
            "exit_open": 111 + rel * 5 if exit_ else None,
            "realized_points": 11 if exit_ else None,
            "realized_return_pct": 11 if exit_ else None,
        }
        out.append(row)
    return out


def test_bootstrap_update_projects_active_bullish_trade_without_invented_start():
    rows = [{
        "stage": "BULLISH_OPTION_SHADOW_UPDATE",
        "status": "ACTIVE",
        "payload": {
            "status": "ACTIVE",
            "signal_bar": "2026-09-24T14:15:00+05:30",
            "signal_boundary": "2026-09-24T14:20:00+05:30",
            "signal_spot": 23450.0,
            "source": "PATH1_ROUTE_B",
            "expiry": "2026-09-29",
            "atm": 23450.0,
            "legs": _legs("CE"),
        },
    }]
    d = project_directional_shadow_dashboard(rows)
    assert d["active_count"] == 1
    t = d["trades"][0]
    assert t["direction"] == "BULLISH"
    assert t["option_side"] == "CE"
    assert t["status"] == "ACTIVE"
    assert len(t["legs"]) == 5


def test_bearish_pe_closed_trade_is_combined_with_exact_five_legs():
    base = {
        "status": "ACTIVE",
        "signal_bar": "2026-09-24T10:30:00+05:30",
        "signal_boundary": "2026-09-24T10:35:00+05:30",
        "signal_spot": 23440.0,
        "source": "PATH1_ROUTE_B",
        "expiry": "2026-09-29",
        "atm": 23450.0,
    }
    rows = [
        {"stage": "BEARISH_OPTION_SHADOW_START", "status": "PASS", "payload": {**base, "legs": _legs("PE")}},
        {"stage": "BEARISH_OPTION_SHADOW_EXIT", "status": "PASS", "payload": {
            **base, "status": "CLOSED", "exit_reason": "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21",
            "legs": _legs("PE", exit_=True),
        }},
    ]
    d = project_directional_shadow_dashboard(rows)
    assert d["complete_closed_count"] == 1
    t = d["trades"][0]
    assert t["direction"] == "BEARISH"
    assert t["option_side"] == "PE"
    assert t["complete"] is True
    assert t["status"] == "CLOSED"


def test_safety_projection_never_contains_quantity_or_rupee_pnl():
    d = project_directional_shadow_dashboard([])
    assert d["quantity"] is None
    assert d["account_pnl_rupees"] is None
    assert d["execution_enabled"] is False
    assert d["paper_order_enabled"] is False
    assert d["option_selection_enabled"] is False
