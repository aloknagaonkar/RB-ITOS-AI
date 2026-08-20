from types import SimpleNamespace

from red_bar_lab.ui.trade_outlook_card import install


def test_full_card_builder_is_enriched_with_observational_outlook():
    module = SimpleNamespace()

    def build(order, telemetry, **kwargs):
        return {
            "status": order.get("status"),
            "option_type": order.get("option_type"),
            "unrealized_pnl": order.get("unrealized_pnl"),
            "entry_price": order.get("entry_price"),
            "current_price": order.get("current_price"),
            "delta_change": -0.12,
            "pcr_change": 0.2,
            "spread_pct": 0.7,
            "freshness": {"status": "FRESH"},
        }

    module.build_active_trade_card = build
    module.render_active_trade_card = lambda st, card: None

    install(module)
    card = module.build_active_trade_card(
        {
            "status": "OPEN",
            "option_type": "PE",
            "entry_price": 100.0,
            "current_price": 112.0,
            "unrealized_pnl": 900.0,
        },
        {},
    )

    assert card["trade_outlook"]["recommendation"] == "HOLD PE"
    assert card["trade_outlook"]["authority"] == "OBSERVATIONAL ONLY"


def test_install_is_idempotent():
    module = SimpleNamespace(
        build_active_trade_card=lambda order, telemetry, **kwargs: {
            "freshness": {"status": "UNAVAILABLE"}
        },
        render_active_trade_card=lambda st, card: None,
    )

    install(module)
    first = module.build_active_trade_card
    install(module)

    assert module.build_active_trade_card is first
