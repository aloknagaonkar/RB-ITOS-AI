from types import SimpleNamespace

from red_bar_lab.ui.current_trade_option_telemetry import install


def _module():
    calls = {"telemetry": 0}

    def safe_latest(database, order_id):
        calls["telemetry"] += 1
        return database.telemetry.get(order_id)

    def safe_checkpoint(database, order):
        return None

    def build_attribution(order, checkpoint, telemetry):
        return {"strategy": "Red Bar", "signal_id": order.get("signal_id")}

    def compact(rows):
        return [
            {
                "Order": row.get("order_id"),
                "Contract": row.get("tradingsymbol"),
                "P&L": row.get("unrealized_pnl"),
            }
            for row in rows
        ]

    return SimpleNamespace(
        _safe_latest_telemetry=safe_latest,
        _safe_checkpoint=safe_checkpoint,
        build_strategy_attribution=build_attribution,
        _attributed_orders=lambda database, orders: list(orders),
        _compact_trade_rows=compact,
        calls=calls,
    )


def test_active_trade_rows_show_selected_strike_pcr_and_delta():
    module = _module()
    install(module)
    database = SimpleNamespace(
        telemetry={
            "O1": {
                "delta": -0.4271,
                "pcr_oi": 1.34,
                "call_oi_at_strike": 120000,
                "put_oi_at_strike": 160800,
                "iv": 14.28,
                "pcr_source": "OPTION_CHAIN_ROW",
                "observed_timestamp": "2026-08-20T10:15:00+05:30",
            }
        }
    )

    attributed = module._attributed_orders(
        database,
        [
            {
                "order_id": "O1",
                "signal_id": "RB-1",
                "tradingsymbol": "NIFTY25000PE",
                "unrealized_pnl": 450.0,
            }
        ],
    )
    rows = module._compact_trade_rows(attributed)

    assert rows[0]["Delta"] == "-0.427"
    assert rows[0]["Strike PCR"] == "1.34"
    assert rows[0]["Call OI"] == "120,000"
    assert rows[0]["Put OI"] == "160,800"
    assert rows[0]["IV"] == "14.28"
    assert rows[0]["PCR Source"] == "OPTION_CHAIN_ROW"
    assert module.calls["telemetry"] == 1


def test_missing_telemetry_is_visible_without_failure():
    module = _module()
    install(module)
    database = SimpleNamespace(telemetry={})

    attributed = module._attributed_orders(
        database,
        [{"order_id": "O2", "tradingsymbol": "NIFTY25100CE"}],
    )
    rows = module._compact_trade_rows(attributed)

    assert rows[0]["Delta"] == "—"
    assert rows[0]["Strike PCR"] == "—"
    assert rows[0]["PCR Source"] == "NOT_AVAILABLE"
