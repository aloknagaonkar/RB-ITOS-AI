from types import SimpleNamespace

from red_bar_lab.execution.paper_close_telemetry_lifecycle import install


def test_successful_close_without_provider_records_latest_fallback(monkeypatch):
    captured = []

    class Engine:
        def __init__(self):
            self.database = SimpleNamespace(
                read_latest_option_execution_telemetry=lambda order_id: {
                    "order_id": order_id,
                    "pcr_oi": 1.31,
                    "delta": -0.51,
                }
            )

        def close_position(self, *, order_id):
            return {"order_id": order_id, "status": "CLOSED"}

    monkeypatch.setattr(
        "red_bar_lab.execution.paper_close_telemetry_lifecycle.record_exit_telemetry_fallback",
        lambda database, order_id, telemetry: captured.append((order_id, telemetry)) or True,
    )

    install(Engine)
    result = Engine().close_position(order_id="O1")

    assert result["status"] == "CLOSED"
    assert captured == [("O1", {"order_id": "O1", "pcr_oi": 1.31, "delta": -0.51})]


def test_close_reuses_same_provider_quote_for_exact_exit_snapshot(monkeypatch):
    exact = []

    class Provider:
        def __init__(self):
            self.calls = 0

        def quote(self, keys):
            self.calls += 1
            return {
                "NFO:NIFTY25000PE": {
                    "last_price": 157.8,
                    "delta": -0.54,
                    "depth": {
                        "buy": [{"price": 157.7}],
                        "sell": [{"price": 157.9}],
                    },
                }
            }

    class Engine:
        def __init__(self):
            self.database = SimpleNamespace(
                read_latest_option_execution_telemetry=lambda order_id: {
                    "order_id": order_id,
                    "pcr_oi": 1.31,
                    "delta": -0.51,
                }
            )

        def close_position(self, *, zerodha, order_id):
            quote = zerodha.quote(["NFO:NIFTY25000PE"])["NFO:NIFTY25000PE"]
            return {
                "order_id": order_id,
                "status": "CLOSED",
                "exchange": "NFO",
                "tradingsymbol": "NIFTY25000PE",
                "exit_timestamp": "2026-08-20T10:30:00+05:30",
                "exit_price": quote["last_price"],
            }

    monkeypatch.setattr(
        "red_bar_lab.execution.paper_close_telemetry_lifecycle.record_exit_telemetry_exact",
        lambda database, order_id, quote, latest, observed_timestamp=None: exact.append(
            (order_id, quote, latest, observed_timestamp)
        ) or True,
    )

    provider = Provider()
    install(Engine)
    result = Engine().close_position(zerodha=provider, order_id="O2")

    assert result["status"] == "CLOSED"
    assert provider.calls == 1
    assert exact[0][0] == "O2"
    assert exact[0][1]["last_price"] == 157.8
    assert exact[0][2]["pcr_oi"] == 1.31
    assert exact[0][3] == "2026-08-20T10:30:00+05:30"


def test_telemetry_failure_never_blocks_completed_close():
    class Engine:
        def __init__(self):
            self.database = SimpleNamespace(
                read_latest_option_execution_telemetry=lambda order_id: (_ for _ in ()).throw(RuntimeError("db"))
            )

        def close_position(self, *, order_id):
            return {"order_id": order_id, "status": "CLOSED"}

    install(Engine)

    assert Engine().close_position(order_id="O3") == {"order_id": "O3", "status": "CLOSED"}


def test_open_result_does_not_record_exit_snapshot(monkeypatch):
    captured = []

    class Engine:
        def __init__(self):
            self.database = SimpleNamespace(
                read_latest_option_execution_telemetry=lambda order_id: {"order_id": order_id}
            )

        def close_position(self, *, order_id):
            return {"order_id": order_id, "status": "OPEN"}

    monkeypatch.setattr(
        "red_bar_lab.execution.paper_close_telemetry_lifecycle.record_exit_telemetry_fallback",
        lambda *args, **kwargs: captured.append(True),
    )

    install(Engine)
    Engine().close_position(order_id="O4")

    assert captured == []
