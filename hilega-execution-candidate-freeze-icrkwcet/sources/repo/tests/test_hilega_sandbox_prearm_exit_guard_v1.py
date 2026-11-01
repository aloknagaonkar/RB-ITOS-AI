from pathlib import Path
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


def test_prearm_exit_skipped_and_next_trade_runs(tmp_path, monkeypatch):
    source=configure_env(monkeypatch,tmp_path)
    append(source,"09:15","ENTRY_OPENING_BULLISH_CONFIRMED")
    p=paths(tmp_path)
    arm_session(session_date=date(2026,10,6),source=source,control=JsonControl(p.control),max_orders=4,confirmation="ARM_UPSTOX_SANDBOX_ONLY",now=NOW)
    append(source,"09:20","STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21")
    fake=FakeExecutor()
    worker=HilegaUpstoxSandboxLiveWorkerV1(paths=p,now_fn=lambda:NOW,executor_factory=lambda _:fake)
    result=worker.run_once()
    assert result["skipped_this_run"]==1
    assert fake.events==[]
    assert JsonControl(p.control).read()["armed"] is True
    assert worker.run_once()["skipped_this_run"]==0
    append(source,"09:25","ENTRY_OPENING_BULLISH_CONFIRMED")
    assert worker.run_once()["orders_sent_this_run"]==1
    append(source,"09:30","STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21")
    assert worker.run_once()["orders_sent_this_run"]==1
    assert [e.event_type for e in fake.events]==["ENTRY","EXIT"]


def test_prearm_guard_requires_proof():
    from market_lab.hilega_sandbox_prearm_exit_guard_v1 import is_prearm_exit
    entry=dict(event_type="ENTRY",decision="WOULD_SUBMIT",trade_id="t",direction="BEARISH",source_sequence=1,event_timestamp="2026-10-06T09:20:00+05:30")
    intent=dict(event_type="EXIT",trade_id="t",direction="BEARISH",event_timestamp="2026-10-06T10:00:00+05:30")
    control=dict(session_date="2026-10-06",baseline_source_sequence=2)
    assert is_prearm_exit(intent,[entry],control,[])
    assert not is_prearm_exit(intent,[],control,[])
    assert not is_prearm_exit(intent,[entry],control,[dict(trade_id="t",status="FAILED")])
    assert not is_prearm_exit(intent,[dict(entry,source_sequence=3)],control,[])
    assert not is_prearm_exit(intent,[dict(entry,direction="BULLISH")],control,[])


def test_postarm_exit_mismatch_still_stops_worker(tmp_path, monkeypatch):
    source=configure_env(monkeypatch,tmp_path)
    p=paths(tmp_path)
    arm_session(session_date=date(2026,10,6),source=source,control=JsonControl(p.control),max_orders=4,confirmation="ARM_UPSTOX_SANDBOX_ONLY",now=NOW)
    append(source,"09:20","ENTRY_OPENING_BULLISH_CONFIRMED")
    append(source,"09:25","STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21")
    # Simulate reconciliation failure after a post-arm entry was dispatched.
    monkeypatch.setenv("HILEGA_SANDBOX_BRIDGE_OBSERVATION_ENABLED","1")
    from market_lab.hilega_sandbox_event_bridge_v1 import HilegaSandboxEventBridgeV1, IntentStore, BridgeConfig
    HilegaSandboxEventBridgeV1(BridgeConfig.from_env()).run_once()
    import os
    entry=next(r for r in IntentStore(Path(os.environ['HILEGA_SANDBOX_BRIDGE_OUTPUT'])).rows() if r.get('event_type')=='ENTRY')
    DispatchStore(p.dispatch).append(dict(intent_id=entry['intent_id'],trade_id=entry['trade_id'],session_date='2026-10-06',status='FAILED',terminal=True))
    fake=FakeExecutor()
    worker=HilegaUpstoxSandboxLiveWorkerV1(paths=p,now_fn=lambda:NOW,executor_factory=lambda _:fake)
    with pytest.raises(LiveWorkerError,match='exit does not match'):
        worker.run_once()
    assert JsonControl(p.control).read()['kill_switch'] is True
    assert fake.events==[]
