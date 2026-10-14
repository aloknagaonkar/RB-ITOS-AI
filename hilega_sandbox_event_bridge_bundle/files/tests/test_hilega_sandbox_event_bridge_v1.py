from datetime import datetime

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
