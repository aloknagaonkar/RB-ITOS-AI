from __future__ import annotations

from types import SimpleNamespace

from red_bar_lab.ui import strategy_query_cache


class _Database:
    def __init__(self):
        self.open_order_reads = 0

    def read_open_paper_execution_orders(self, strategy):
        self.open_order_reads += 1
        return [{"strategy": strategy}]

    def marker(self):
        return "delegated"


def test_proxy_routes_only_approved_observational_reads(monkeypatch):
    calls = []

    def option_rows(database_path, instrument_key, start_date, end_date, limit=500):
        calls.append(("options", database_path, instrument_key, start_date, end_date, limit))
        return [{"kind": "option"}]

    def reference_rows(database_path, instrument_key, trading_date):
        calls.append(("levels", database_path, instrument_key, trading_date))
        return [{"kind": "level"}]

    monkeypatch.setattr(
        strategy_query_cache,
        "read_option_chain_history_cached",
        option_rows,
    )
    monkeypatch.setattr(
        strategy_query_cache,
        "read_reference_levels_cached",
        reference_rows,
    )

    database = _Database()
    proxy = strategy_query_cache.StrategyObservationalDatabaseProxy(
        database,
        "runs/red_bar.db",
    )

    assert proxy.read_option_chain_history(
        "NSE_INDEX|Nifty 50", "2026-08-17", "2026-08-17", limit=25
    ) == [{"kind": "option"}]
    assert proxy.read_reference_levels(
        "NSE_INDEX|Nifty 50", "2026-08-17"
    ) == [{"kind": "level"}]
    assert proxy.marker() == "delegated"

    # Execution-sensitive reads must pass through to the live database object.
    assert proxy.read_open_paper_execution_orders("PAPER-STD") == [
        {"strategy": "PAPER-STD"}
    ]
    assert database.open_order_reads == 1
    assert calls == [
        (
            "options",
            "runs/red_bar.db",
            "NSE_INDEX|Nifty 50",
            "2026-08-17",
            "2026-08-17",
            25,
        ),
        (
            "levels",
            "runs/red_bar.db",
            "NSE_INDEX|Nifty 50",
            "2026-08-17",
        ),
    ]


def test_render_wrapper_injects_proxy_without_changing_page_arguments():
    captured = {}

    def render_page(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        captured.update(
            settings=settings,
            layout=layout,
            database=database,
            token=token,
            underlying_name=underlying_name,
            instrument_key=instrument_key,
            interval=interval,
        )
        return "rendered"

    wrapped = strategy_query_cache.build_strategy_query_cache_wrapper(render_page)
    settings = SimpleNamespace(database_path="runs/red_bar.db")
    database = _Database()

    assert wrapped(
        settings,
        "layout",
        database,
        "token",
        "NIFTY 50",
        "NSE_INDEX|Nifty 50",
        1,
    ) == "rendered"
    assert isinstance(
        captured["database"],
        strategy_query_cache.StrategyObservationalDatabaseProxy,
    )
    assert captured["database"]._database is database
    assert captured["token"] == "token"
    assert captured["instrument_key"] == "NSE_INDEX|Nifty 50"
    assert captured["interval"] == 1


def test_cache_module_does_not_define_execution_sensitive_cached_readers():
    source = strategy_query_cache.__file__
    text = open(source, encoding="utf-8").read()

    assert "read_option_chain_history_cached" in text
    assert "read_reference_levels_cached" in text
    assert "read_open_paper_execution_orders_cached" not in text
    assert "read_active_positions_cached" not in text
    assert "kill_switch" not in text
