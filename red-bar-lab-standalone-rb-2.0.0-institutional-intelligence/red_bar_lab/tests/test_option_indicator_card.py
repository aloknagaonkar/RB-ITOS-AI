from types import SimpleNamespace

from red_bar_lab.ui.option_indicator_card import (
    classify_entry_vwap_distance,
    install,
)


def _module():
    return SimpleNamespace(
        build_active_trade_card=lambda order, telemetry, lifecycle=None, now=None: {
            "status": order.get("status", "OPEN"),
            "entry_price": order.get("entry_price"),
            "comparison_label": "Exit" if order.get("status") == "CLOSED" else "Current",
        },
        render_active_trade_card=lambda st, card: None,
    )


def test_open_card_uses_latest_vwap_and_rsi():
    module = _module()
    install(module)
    card = module.build_active_trade_card(
        {"status": "OPEN", "entry_price": 100.5},
        {},
        lifecycle={
            "entry": {"option_vwap": 100.0, "option_rsi14": 48.0},
            "latest": {
                "option_vwap": 104.0,
                "option_rsi14": 62.0,
                "indicator_source": "PERSISTED_OPTION_TELEMETRY",
            },
        },
    )
    assert card["current_option_vwap"] == 104.0
    assert card["option_vwap_change"] == 4.0
    assert card["current_option_rsi14"] == 62.0
    assert card["option_rsi14_change"] == 14.0
    assert card["entry_vwap_distance_class"] == "CLOSE"
    assert card["entry_vwap_relation"] == "ABOVE VWAP"
    assert card["entry_vwap_distance_points"] == 0.5
    assert card["entry_vwap_distance_pct"] == 0.5


def test_closed_card_uses_exit_vwap_and_rsi():
    module = _module()
    install(module)
    card = module.build_active_trade_card(
        {"status": "CLOSED", "entry_price": 99.8},
        {},
        lifecycle={
            "entry": {"option_vwap": 100.0, "option_rsi14": 50.0},
            "latest": {"option_vwap": 105.0, "option_rsi14": 60.0},
            "exit": {
                "option_vwap": 103.0,
                "option_rsi14": 55.0,
                "indicator_source": "PERSISTED_OPTION_TELEMETRY",
            },
        },
    )
    assert card["current_option_vwap"] == 103.0
    assert card["current_option_rsi14"] == 55.0
    assert card["entry_vwap_distance_class"] == "VERY CLOSE"
    assert card["entry_vwap_relation"] == "BELOW VWAP"


def test_entry_vwap_distance_bands_are_deterministic():
    very_close = classify_entry_vwap_distance(100.25, 100.0)
    close = classify_entry_vwap_distance(100.75, 100.0)
    far = classify_entry_vwap_distance(101.5, 100.0)
    very_far = classify_entry_vwap_distance(101.51, 100.0)

    assert very_close["classification"] == "VERY CLOSE"
    assert close["classification"] == "CLOSE"
    assert far["classification"] == "FAR"
    assert very_far["classification"] == "VERY FAR"


def test_entry_vwap_distance_is_unavailable_without_valid_values():
    result = classify_entry_vwap_distance(None, 100.0)

    assert result == {
        "classification": "UNAVAILABLE",
        "distance_points": None,
        "distance_pct": None,
        "relation": "UNKNOWN",
    }
