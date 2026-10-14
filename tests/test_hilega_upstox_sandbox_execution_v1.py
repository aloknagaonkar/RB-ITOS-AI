from datetime import datetime

import pytest

from market_lab.hilega_upstox_sandbox_execution_v1 import (
    HilegaExecutionEvent,
    HilegaSandboxExecutor,
    JsonlJournal,
    SandboxConfig,
    SandboxExecutionError,
)


class FakeTransport:
    def __init__(self):
        self.orders = []

    def resolve_atm(self, direction, session_date):
        return {
            "spot": 22555.75,
            "expiry": "2026-10-06",
            "strike": 22550.0,
            "option_type": "CE" if direction == "BULLISH" else "PE",
            "instrument_key": "NSE_FO|CE" if direction == "BULLISH" else "NSE_FO|PE",
            "lot_size": 65,
        }

    def place_market(self, **payload):
        self.orders.append(payload)
        return f"order-{len(self.orders)}"


def config(tmp_path, *, enabled=True, kill=False):
    return SandboxConfig(
        enabled=enabled,
        kill_switch=kill,
        lots=1,
        max_orders_per_session=20,
        analytics_token="analytics",
        sandbox_token="sandbox",
        journal_path=tmp_path / "events.jsonl",
    )


def event(event_id="entry-1", trade_id="trade-1", event_type="ENTRY", direction="BULLISH"):
    return HilegaExecutionEvent(
        event_id=event_id,
        trade_id=trade_id,
        event_type=event_type,
        direction=direction,
        event_timestamp="2026-10-05T10:00:00+05:30",
    )


def test_disabled_and_kill_switch_block_before_transport(tmp_path):
    for cfg in (config(tmp_path, enabled=False), config(tmp_path, kill=True)):
        transport = FakeTransport()
        with pytest.raises(SandboxExecutionError):
            HilegaSandboxExecutor(cfg, transport, JsonlJournal(cfg.journal_path)).process(
                event(), "SANDBOX_ONLY"
            )
        assert transport.orders == []


def test_confirmation_is_mandatory(tmp_path):
    cfg = config(tmp_path)
    with pytest.raises(SandboxExecutionError, match="SANDBOX_ONLY"):
        HilegaSandboxExecutor(cfg, FakeTransport(), JsonlJournal(cfg.journal_path)).process(event(), "")


@pytest.mark.parametrize(
    ("direction", "option", "instrument"),
    [("BULLISH", "CE", "NSE_FO|CE"), ("BEARISH", "PE", "NSE_FO|PE")],
)
def test_entry_maps_direction_and_dynamic_lot(direction, option, instrument, tmp_path):
    cfg = config(tmp_path)
    transport = FakeTransport()
    result = HilegaSandboxExecutor(cfg, transport, JsonlJournal(cfg.journal_path)).process(
        event(direction=direction), "SANDBOX_ONLY"
    )
    assert result["contract"]["option_type"] == option
    assert result["contract"]["instrument_key"] == instrument
    assert result["quantity"] == 65
    assert transport.orders[0]["transaction_type"] == "BUY"


def test_same_event_is_idempotent(tmp_path):
    cfg = config(tmp_path)
    transport = FakeTransport()
    executor = HilegaSandboxExecutor(cfg, transport, JsonlJournal(cfg.journal_path))
    first = executor.process(event(), "SANDBOX_ONLY")
    second = executor.process(event(), "SANDBOX_ONLY")
    assert first["broker_order_id"] == second["broker_order_id"]
    assert second["idempotent_replay"] is True
    assert len(transport.orders) == 1


def test_exit_sells_exact_entry_contract_and_quantity(tmp_path):
    cfg = config(tmp_path)
    transport = FakeTransport()
    executor = HilegaSandboxExecutor(cfg, transport, JsonlJournal(cfg.journal_path))
    executor.process(event(), "SANDBOX_ONLY")
    result = executor.process(event("exit-1", event_type="EXIT"), "SANDBOX_ONLY")
    assert result["contract"]["instrument_key"] == "NSE_FO|CE"
    assert result["quantity"] == 65
    assert transport.orders[-1]["transaction_type"] == "SELL"


def test_exit_without_entry_is_rejected(tmp_path):
    cfg = config(tmp_path)
    with pytest.raises(SandboxExecutionError, match="no accepted open entry"):
        HilegaSandboxExecutor(cfg, FakeTransport(), JsonlJournal(cfg.journal_path)).process(
            event(event_type="EXIT"), "SANDBOX_ONLY"
        )


def test_non_terminal_request_is_never_retried(tmp_path):
    cfg = config(tmp_path)
    journal = JsonlJournal(cfg.journal_path)
    journal.append({"event_id": "entry-1", "trade_id": "trade-1", "status": "REQUESTED", "terminal": False})
    transport = FakeTransport()
    with pytest.raises(SandboxExecutionError, match="reconcile"):
        HilegaSandboxExecutor(cfg, transport, journal).process(event(), "SANDBOX_ONLY")
    assert transport.orders == []


def test_event_validation_rejects_ambiguous_identity():
    with pytest.raises(SandboxExecutionError):
        HilegaExecutionEvent.from_dict(
            {
                "event_id": "",
                "trade_id": "x",
                "event_type": "ENTRY",
                "direction": "BULLISH",
                "event_timestamp": datetime.now().astimezone().isoformat(),
            }
        )
