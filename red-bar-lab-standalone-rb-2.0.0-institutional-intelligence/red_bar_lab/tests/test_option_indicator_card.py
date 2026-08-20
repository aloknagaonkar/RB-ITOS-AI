from types import SimpleNamespace

from red_bar_lab.ui.option_indicator_card import install


def _module():
    return SimpleNamespace(
        build_active_trade_card=lambda order, telemetry, lifecycle=None, now=None: {
            "status": order.get("status", "OPEN"),
            "comparison_label": "Exit" if order.get("status") == "CLOSED" else "Current",
        },
        render_active_trade_card=lambda st, card: None,
    )


def test_open_card_uses_latest_vwap_and_rsi():
    module = _module()
    install(module)
    card = module.build_active_trade_card(
        {"status": "OPEN"},
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


def test_closed_card_uses_exit_vwap_and_rsi():
    module = _module()
    install(module)
    card = module.build_active_trade_card(
        {"status": "CLOSED"},
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
