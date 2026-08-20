from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.ui.full_trade_card import build_active_trade_card


IST = ZoneInfo("Asia/Kolkata")


def test_active_pe_card_uses_selected_put_oi_and_persisted_telemetry():
    card = build_active_trade_card(
        {
            "order_id": "O1",
            "status": "OPEN",
            "tradingsymbol": "NIFTY25000PE",
            "option_type": "PE",
            "strike": 25000,
            "expiry": "2026-08-27",
            "quantity": 75,
            "entry_price": 142.5,
            "current_price": 161.2,
            "unrealized_pnl": 1402.5,
            "execution_strategy_source": "RED_BAR_V2",
        },
        {
            "pcr_oi": 1.46,
            "delta": -0.57,
            "call_oi_at_strike": 820000,
            "put_oi_at_strike": 1197200,
            "iv": 15.1,
            "pcr_source": "OPTION_CHAIN_ROW",
            "observed_timestamp": "2026-08-20T10:30:00+05:30",
        },
        now=datetime(2026, 8, 20, 10, 30, 12, tzinfo=IST),
    )

    assert card["current_action"] == "HOLD PE"
    assert card["current_pcr"] == 1.46
    assert card["current_delta"] == -0.57
    assert card["selected_oi"] == 1197200
    assert card["freshness"]["status"] == "FRESH"
    assert card["freshness"]["age_seconds"] == 12
    assert card["authority"] == "OBSERVATIONAL ONLY"


def test_active_ce_card_uses_selected_call_oi():
    card = build_active_trade_card(
        {"order_id": "O2", "status": "OPEN", "tradingsymbol": "NIFTY25100CE", "option_type": "CE"},
        {"call_oi_at_strike": 640000, "put_oi_at_strike": 510000},
    )

    assert card["current_action"] == "HOLD CE"
    assert card["selected_oi"] == 640000
    assert card["freshness"]["status"] == "UNAVAILABLE"


def test_entry_and_active_lifecycle_values_are_shown_with_changes():
    card = build_active_trade_card(
        {"order_id": "O3", "status": "OPEN", "tradingsymbol": "NIFTY24900PE", "option_type": "PE"},
        {"pcr_oi": 1.46, "delta": -0.57},
        lifecycle={
            "entry": {
                "snapshot_type": "ENTRY",
                "pcr_oi": 1.18,
                "delta": -0.42,
                "snapshot_source": "ACTIVE_CAPTURE",
                "observed_timestamp": "2026-08-20T10:12:00+05:30",
            },
            "latest": {
                "snapshot_type": "ACTIVE",
                "pcr_oi": 1.46,
                "delta": -0.57,
                "put_oi_at_strike": 1197200,
                "call_oi_at_strike": 820000,
                "snapshot_source": "ACTIVE_CAPTURE",
                "observed_timestamp": "2026-08-20T10:30:00+05:30",
            },
            "exit": None,
        },
    )

    assert card["entry_pcr"] == 1.18
    assert card["current_pcr"] == 1.46
    assert round(card["pcr_change"], 2) == 0.28
    assert card["entry_delta"] == -0.42
    assert card["current_delta"] == -0.57
    assert round(card["delta_change"], 2) == -0.15
    assert card["selected_oi"] == 1197200
    assert "persisted" in card["lifecycle_note"]


def test_closed_card_uses_exit_lifecycle_snapshot():
    card = build_active_trade_card(
        {
            "order_id": "O4",
            "status": "CLOSED",
            "tradingsymbol": "NIFTY25000PE",
            "option_type": "PE",
            "entry_price": 142.5,
            "exit_price": 157.8,
            "realized_pnl": 1147.5,
        },
        None,
        lifecycle={
            "entry": {"pcr_oi": 1.18, "delta": -0.42, "snapshot_source": "ACTIVE_CAPTURE"},
            "latest": {"pcr_oi": 1.46, "delta": -0.57},
            "exit": {
                "pcr_oi": 1.32,
                "delta": -0.51,
                "snapshot_source": "LAST_ACTIVE_FALLBACK",
                "data_quality": "FALLBACK",
            },
        },
    )

    assert card["comparison_label"] == "Exit"
    assert card["current_action"] == "CLOSED"
    assert card["current_pcr"] == 1.32
    assert card["current_delta"] == -0.51
    assert card["exit_snapshot_source"] == "LAST_ACTIVE_FALLBACK"
    assert card["exit_data_quality"] == "FALLBACK"
