from datetime import datetime
import json

import pytest

from market_lab.hilega_sandbox_event_bridge_v1 import (
    BridgeConfig,
    BridgeError,
    HilegaSandboxEventBridgeV1,
    IntentStore,
)
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


def config(tmp_path, enabled=True):
    return BridgeConfig(enabled, tmp_path / "audit.jsonl", tmp_path / "intents.jsonl")


def append(store, minute, events, *, stage="DIRECTIONAL_DECISION", status="PROCESSED"):
    ts = datetime.fromisoformat(f"2026-10-06T{minute}:00+05:30")
    store.append(
        event_time=ts,
        checkpoint=ts,
        stage=stage,
        status=status,
        payload={"bar_timestamp": ts.isoformat(), "accepted_events": events},
    )


def test_disabled_bridge_never_processes(tmp_path):
    cfg = config(tmp_path, False)
    cfg.source.touch()
    with pytest.raises(BridgeError, match="not 1"):
        HilegaSandboxEventBridgeV1(cfg).run_once()


def test_bullish_entry_exit_produces_ce_buy_sell_without_broker(tmp_path):
    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    append(source, "09:20", ["ENTRY_OPENING_BULLISH_CONFIRMED"])
    append(source, "10:10", ["STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"])
    result = HilegaSandboxEventBridgeV1(cfg).run_once()
    rows = IntentStore(cfg.output).rows()
    assert [row["transaction_type"] for row in rows] == ["BUY", "SELL"]
    assert {row["option_type"] for row in rows} == {"CE"}
    assert rows[0]["trade_id"] == rows[1]["trade_id"]
    assert all(row["decision"] == "WOULD_SUBMIT" for row in rows)
    assert all(row["broker_called"] is False for row in rows)
    assert result["open_trade_ids"] == {}


def test_bearish_maps_to_pe_and_restart_is_idempotent(tmp_path):
    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    append(source, "11:05", ["ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21"])
    bridge = HilegaSandboxEventBridgeV1(cfg)
    first = bridge.run_once()
    second = bridge.run_once()
    rows = IntentStore(cfg.output).rows()
    assert first["written"] == 1
    assert second["written"] == 0
    assert second["idempotent_ignored"] == 1
    assert len(rows) == 1
    assert rows[0]["option_type"] == "PE"
    assert rows[0]["transaction_type"] == "BUY"


def test_suppressed_or_nonprocessed_events_are_ignored(tmp_path):
    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    ts = datetime.fromisoformat("2026-10-06T09:20:00+05:30")
    source.append(
        event_time=ts,
        checkpoint=ts,
        stage="DIRECTIONAL_DECISION",
        status="PROCESSED",
        payload={
            "accepted_events": [],
            "suppressed_events": ["ENTRY_OPENING_BULLISH_CONFIRMED"],
        },
    )
    append(source, "09:25", ["ENTRY_OPENING_BULLISH_CONFIRMED"], status="FAILED")
    assert HilegaSandboxEventBridgeV1(cfg).run_once()["written"] == 0


def test_exit_without_observed_entry_is_audited_but_blocked(tmp_path):
    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    append(source, "10:10", ["STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"])
    result = HilegaSandboxEventBridgeV1(cfg).run_once()
    row = IntentStore(cfg.output).rows()[0]
    assert result["blocked"] == 1
    assert row["decision"] == "WOULD_NOT_SUBMIT"
    assert row["reason_code"] == "NO_OPEN_BRIDGE_TRADE"
    assert row["trade_id"] is None


def test_tampered_source_audit_fails_closed(tmp_path):
    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    append(source, "09:20", ["ENTRY_OPENING_BULLISH_CONFIRMED"])
    cfg.source.write_text(cfg.source.read_text().replace("BULLISH", "BEARISH", 1))
    with pytest.raises(BridgeError, match="integrity failed"):
        HilegaSandboxEventBridgeV1(cfg).run_once()


def test_multiple_execution_actions_in_one_audit_row_fail_closed(tmp_path):
    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    append(
        source,
        "09:20",
        ["ENTRY_OPENING_BULLISH_CONFIRMED", "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"],
    )
    with pytest.raises(BridgeError, match="ambiguous"):
        HilegaSandboxEventBridgeV1(cfg).run_once()


def test_verified_manual_reset_releases_bridge_trade_without_replaying_old_entry(tmp_path, monkeypatch):
    import market_lab.hilega_sandbox_event_bridge_v1 as bridge_module

    cfg = config(tmp_path)
    source = ShadowStepAuditStoreV1(cfg.source)
    strategy = "HILEGA_V2_ALIGNMENT_DUAL_EXIT"
    at = datetime.fromisoformat("2026-10-06T10:00:00+05:30")
    source.append(event_time=at, checkpoint=at, stage="DIRECTIONAL_DECISION",
                  status="PROCESSED", payload=dict(strategy_id=strategy,
                  decision_timestamp=at.isoformat(), accepted_events=["ENTRY_OPENING_BULLISH_CONFIRMED"]))
    first = HilegaSandboxEventBridgeV1(cfg).run_once()
    assert first["written"] == 1
    old_trade = IntentStore(cfg.output).rows()[0]["trade_id"]
    blocked_at = datetime.fromisoformat("2026-10-06T10:03:00+05:30")
    source.append(event_time=blocked_at, checkpoint=blocked_at, stage="DIRECTIONAL_DECISION",
                  status="PROCESSED", payload=dict(strategy_id=strategy,
                  decision_timestamp=blocked_at.isoformat(), accepted_events=["ENTRY_OPENING_BULLISH_CONFIRMED"]))
    HilegaSandboxEventBridgeV1(cfg).run_once()
    blocked_before = IntentStore(cfg.output).rows()[-1]
    assert blocked_before['decision'] == 'WOULD_NOT_SUBMIT'
    root = tmp_path / "manual"
    root.mkdir()
    monkeypatch.setattr(bridge_module, "MANUAL_EXIT_ROOT", root)
    request_id = "verified-reset"
    completed = "2026-10-06T10:05:00+05:30"
    (root / "manual-exit.json").write_text(json.dumps({"requests": [dict(
        request_id=request_id, status="READY_FOR_FRESH_SIGNAL", strategy_id=strategy, session_date="2026-10-06",
        completed_at=completed, trade_ids=[old_trade])]}))
    (root / "manual-reset-acks.json").write_text(json.dumps({request_id: {"applied_at": completed, "completed_at": completed}}))
    reset_at = datetime.fromisoformat(completed)
    source.append(event_time=reset_at, checkpoint=reset_at, stage="DIRECTIONAL_MANUAL_EXIT_RESET",
                  status="PROCESSED", payload=dict(strategy_id=strategy, request_id=request_id,
                  completed_at=completed, trade_owner_after="NONE", accepted_events=[]))
    fresh_at = datetime.fromisoformat("2026-10-06T10:10:00+05:30")
    source.append(event_time=fresh_at, checkpoint=fresh_at, stage="DIRECTIONAL_DECISION",
                  status="PROCESSED", payload=dict(strategy_id=strategy,
                  decision_timestamp=fresh_at.isoformat(), accepted_events=["ENTRY_OPENING_BULLISH_CONFIRMED"]))
    bridge = HilegaSandboxEventBridgeV1(cfg)
    assert bridge.run_once()["written"] == 2
    rows = IntentStore(cfg.output).rows()
    assert [row["event_type"] for row in rows] == ["ENTRY", "ENTRY", "RESET", "ENTRY"]
    assert rows[1] == blocked_before
    assert rows[-1]["decision"] == "WOULD_SUBMIT"
    assert rows[-1]["trade_id"] != old_trade
    assert bridge.run_once()["written"] == 0


@pytest.mark.parametrize('fault', ['missing_ack','wrong_trade','wrong_completion','early_ack','wrong_session'])
def test_unverified_manual_reset_cannot_release_trade(tmp_path, monkeypatch, fault):
    import market_lab.hilega_sandbox_event_bridge_v1 as module
    cfg=config(tmp_path);source=ShadowStepAuditStoreV1(cfg.source)
    strategy='HILEGA_V2_ALIGNMENT_DUAL_EXIT'
    def emit(time,stage,**payload):
        at=datetime.fromisoformat('2026-10-06T'+time+':00+05:30')
        source.append(event_time=at,checkpoint=at,stage=stage,status='PROCESSED',
                      payload=dict(strategy_id=strategy,decision_timestamp=at.isoformat(),**payload))
    emit('10:00','DIRECTIONAL_DECISION',accepted_events=['ENTRY_OPENING_BULLISH_CONFIRMED'])
    bridge=HilegaSandboxEventBridgeV1(cfg);bridge.run_once()
    old=IntentStore(cfg.output).rows()[0]['trade_id']
    root=tmp_path/'manual';root.mkdir();monkeypatch.setattr(module,'MANUAL_EXIT_ROOT',root)
    completed='2026-10-06T10:05:00+05:30'
    request=dict(request_id='reset',status='READY_FOR_FRESH_SIGNAL',session_date='2026-10-06',
                 strategy_id=strategy,completed_at=completed,trade_ids=[old])
    ack=dict(completed_at=completed,applied_at=completed)
    if fault=='wrong_trade':request['trade_ids']=['other']
    if fault=='wrong_completion':request['completed_at']='2026-10-06T10:04:00+05:30'
    if fault=='early_ack':ack['applied_at']='2026-10-06T10:04:00+05:30'
    if fault=='wrong_session':request['session_date']='2026-10-05'
    (root/'manual-exit.json').write_text(json.dumps({'requests':[request]}))
    if fault!='missing_ack':(root/'manual-reset-acks.json').write_text(json.dumps({'reset':ack}))
    emit('10:05','DIRECTIONAL_MANUAL_EXIT_RESET',request_id='reset',completed_at=completed,trade_owner_after='NONE',accepted_events=[])
    emit('10:10','DIRECTIONAL_DECISION',accepted_events=['ENTRY_OPENING_BULLISH_CONFIRMED'])
    bridge.run_once()
    assert IntentStore(cfg.output).rows()[-1]['reason_code']=='DIRECTION_ALREADY_OPEN'
    assert not any(r['event_type']=='RESET' for r in IntentStore(cfg.output).rows())
