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


def test_entry_lifecycle_values_are_not_invented_before_snapshot_support():
    card = build_active_trade_card(
        {"order_id": "O3", "status": "OPEN", "tradingsymbol": "NIFTY24900PE", "option_type": "PE"},
        {"pcr_oi": 1.2, "delta": -0.41},
    )

    assert card["entry_pcr"] is None
    assert card["entry_delta"] is None
    assert "explicit lifecycle snapshots" in card["lifecycle_note"]
