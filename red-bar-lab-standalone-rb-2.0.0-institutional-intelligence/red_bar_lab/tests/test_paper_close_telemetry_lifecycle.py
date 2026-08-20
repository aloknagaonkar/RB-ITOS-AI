from types import SimpleNamespace

from red_bar_lab.execution.paper_close_telemetry_lifecycle import install


def test_successful_close_records_latest_telemetry(monkeypatch):
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


def test_telemetry_failure_never_blocks_completed_close():
    class Engine:
        def __init__(self):
            self.database = SimpleNamespace(
                read_latest_option_execution_telemetry=lambda order_id: (_ for _ in ()).throw(RuntimeError("db"))
            )

        def close_position(self, *, order_id):
            return {"order_id": order_id, "status": "CLOSED"}

    install(Engine)

    assert Engine().close_position(order_id="O2") == {"order_id": "O2", "status": "CLOSED"}


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
    Engine().close_position(order_id="O3")

    assert captured == []
