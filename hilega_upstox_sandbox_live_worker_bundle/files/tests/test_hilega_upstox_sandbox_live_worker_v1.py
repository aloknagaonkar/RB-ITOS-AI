from datetime import date, datetime

import pytest

from market_lab.hilega_upstox_sandbox_live_worker_v1 import (
    DispatchStore,
    HilegaUpstoxSandboxLiveWorkerV1,
    JsonControl,
    LiveWorkerError,
    LiveWorkerPaths,
    arm_session,
)
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


NOW = datetime.fromisoformat("2026-10-06T09:15:00+05:30")


class FakeExecutor:
    def __init__(self):
        self.events = []

    def process(self, event, confirmation):
        self.events.append(event)
        option = "CE" if event.direction == "BULLISH" else "PE"
        return {
            "broker_order_id": f"order-{len(self.events)}",
            "contract": {"instrument_key": f"NSE_FO|{option}", "option_type": option},
            "quantity": 65,
            "transaction_type": "BUY" if event.event_type == "ENTRY" else "SELL",
        }


def paths(tmp_path):
    return LiveWorkerPaths(tmp_path / "control.json", tmp_path / "dispatch.jsonl")


def configure_env(monkeypatch, tmp_path):
    source = tmp_path / "audit.jsonl"
    output = tmp_path / "intents.jsonl"
    broker = tmp_path / "broker.jsonl"
    monkeypatch.setenv("HILEGA_SANDBOX_BRIDGE_SOURCE", str(source))
    monkeypatch.setenv("HILEGA_SANDBOX_BRIDGE_OUTPUT", str(output))
    monkeypatch.setenv("HILEGA_UPSTOX_SANDBOX_JOURNAL", str(broker))
    monkeypatch.setenv("HILEGA_UPSTOX_SANDBOX_ENABLED", "1")
    monkeypatch.setenv("HILEGA_UPSTOX_SANDBOX_KILL_SWITCH", "0")
    monkeypatch.setenv("HILEGA_UPSTOX_SANDBOX_LOTS", "1")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "analytics")
    monkeypatch.setenv("UPSTOX_SANDBOX_ACCESS_TOKEN", "sandbox")
    return source


def append(source, minute, event):
    ts = datetime.fromisoformat(f"2026-10-06T{minute}:00+05:30")
    ShadowStepAuditStoreV1(source).append(
        event_time=ts,
        checkpoint=ts,
        stage="DIRECTIONAL_DECISION",
        status="PROCESSED",
        payload={"bar_timestamp": ts.isoformat(), "accepted_events": [event]},
    )


def test_arm_uses_current_audit_sequence_as_historical_fence(tmp_path):
    source = tmp_path / "audit.jsonl"
    append(source, "09:15", "ENTRY_OPENING_BULLISH_CONFIRMED")
    control = JsonControl(tmp_path / "control.json")
    result = arm_session(
        session_date=date(2026, 10, 6),
        source=source,
        control=control,
        max_orders=10,
        confirmation="ARM_UPSTOX_SANDBOX_ONLY",
        now=NOW,
    )
    assert result["baseline_source_sequence"] == 1
    assert result["live_execution_enabled"] is False


def test_historical_rows_before_arm_are_never_submitted(tmp_path, monkeypatch):
    source = configure_env(monkeypatch, tmp_path)
    append(source, "09:15", "ENTRY_OPENING_BULLISH_CONFIRMED")
    p = paths(tmp_path)
    arm_session(
        session_date=date(2026, 10, 6), source=source, control=JsonControl(p.control),
        max_orders=10, confirmation="ARM_UPSTOX_SANDBOX_ONLY", now=NOW,
    )
    fake = FakeExecutor()
    worker = HilegaUpstoxSandboxLiveWorkerV1(
        paths=p, now_fn=lambda: NOW, executor_factory=lambda _: fake
    )
    result = worker.run_once()
    assert result["orders_sent_this_run"] == 0
    assert fake.events == []


def test_new_entry_and_exit_are_submitted_once(tmp_path, monkeypatch):
    source = configure_env(monkeypatch, tmp_path)
    p = paths(tmp_path)
    arm_session(
        session_date=date(2026, 10, 6), source=source, control=JsonControl(p.control),
        max_orders=10, confirmation="ARM_UPSTOX_SANDBOX_ONLY", now=NOW,
    )
    fake = FakeExecutor()
    worker = HilegaUpstoxSandboxLiveWorkerV1(
        paths=p, now_fn=lambda: NOW, executor_factory=lambda _: fake
    )
    append(source, "09:20", "ENTRY_OPENING_BULLISH_CONFIRMED")
    first = worker.run_once()
    assert first["orders_sent_this_run"] == 1
    assert fake.events[0].event_type == "ENTRY"
    assert first["open_trade_id"]
    append(source, "09:25", "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21")
    second = worker.run_once()
    third = worker.run_once()
    assert second["orders_sent_this_run"] == 1
    assert fake.events[-1].event_type == "EXIT"
    assert second["open_trade_id"] is None
    assert third["orders_sent_this_run"] == 0
    assert len(fake.events) == 2


def test_worker_waits_outside_exact_armed_date(tmp_path, monkeypatch):
    source = configure_env(monkeypatch, tmp_path)
    p = paths(tmp_path)
    arm_session(
        session_date=date(2026, 10, 7), source=source, control=JsonControl(p.control),
        max_orders=10, confirmation="ARM_UPSTOX_SANDBOX_ONLY", now=NOW,
    )
    worker = HilegaUpstoxSandboxLiveWorkerV1(
        paths=p, now_fn=lambda: NOW, executor_factory=lambda _: FakeExecutor()
    )
    assert worker.run_once()["status"] == "WAITING_FOR_ARMED_SESSION"


def test_bad_sandbox_config_engages_kill_switch(tmp_path, monkeypatch):
    source = configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HILEGA_UPSTOX_SANDBOX_KILL_SWITCH", "1")
    p = paths(tmp_path)
    arm_session(
        session_date=date(2026, 10, 6), source=source, control=JsonControl(p.control),
        max_orders=10, confirmation="ARM_UPSTOX_SANDBOX_ONLY", now=NOW,
    )
    worker = HilegaUpstoxSandboxLiveWorkerV1(paths=p, now_fn=lambda: NOW)
    with pytest.raises(LiveWorkerError):
        worker.run_once()
    control = JsonControl(p.control).read()
    assert control["kill_switch"] is True
    assert control["armed"] is False


def test_dispatch_rejects_multiple_open_trades(tmp_path):
    store = DispatchStore(tmp_path / "dispatch.jsonl")
    for trade in ("one", "two"):
        store.append(
            {
                "session_date": "2026-10-06", "status": "ACCEPTED", "terminal": True,
                "event_type": "ENTRY", "trade_id": trade,
            }
        )
    with pytest.raises(LiveWorkerError, match="multiple open"):
        store.open_trade("2026-10-06")
