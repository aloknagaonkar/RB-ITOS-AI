import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime

from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1


class DummySources:
    pass


def test_v622_adapter_reads_new_audit_and_feeds_candle(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MIDPOINT_V62_OOS_COLLECTOR_ENABLED", "1")
    ledger = tmp_path / "ledger.csv"
    monkeypatch.setenv("MIDPOINT_V62_OOS_LEDGER", str(ledger))
    audit = tmp_path / "audit.jsonl"

    c = MidpointLiveShadowCoordinatorV1(
        market_sources=DummySources(),
        audit_path=audit,
    )

    rescue = {
        "event_type": "CAP20_RESCUE_TRIGGERED",
        "event_timestamp": "2026-09-29T10:00:00+05:30",
        "direction": "BULLISH",
        "underlying_price": 100.0,
        "family": "B",
    }
    reentry = {
        "event_type": "POST_RESCUE_REENTRY_TRIGGERED",
        "event_timestamp": "2026-09-29T10:05:00+05:30",
        "direction": "BULLISH",
        "underlying_price": 105.0,
        "family": "B",
    }
    audit.write_text(json.dumps(rescue) + "\n" + json.dumps(reentry) + "\n")

    candle = SimpleNamespace(high=126.0, low=118.0, close=124.0)
    c._v621_observe_completed_minute(
        ts=datetime.fromisoformat("2026-09-29T10:06:00+05:30"),
        underlying=candle,
    )

    snap = c._v621_collector.active_snapshot()
    assert len(snap) == 1
    assert snap[0]["r1_armed"] is True
    assert snap[0]["r2_armed"] is True
    assert snap[0]["r1_exit_price"] is None
    assert snap[0]["r2_exit_price"] is None


def test_v622_terminal_is_finalized_after_same_candle_policy(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MIDPOINT_V62_OOS_COLLECTOR_ENABLED", "1")
    ledger = tmp_path / "ledger.csv"
    monkeypatch.setenv("MIDPOINT_V62_OOS_LEDGER", str(ledger))
    audit = tmp_path / "audit.jsonl"

    c = MidpointLiveShadowCoordinatorV1(
        market_sources=DummySources(),
        audit_path=audit,
    )

    events = [
        {
            "event_type": "CAP20_RESCUE_TRIGGERED",
            "event_timestamp": "2026-09-29T10:00:00+05:30",
            "direction": "BULLISH",
            "underlying_price": 100.0,
            "family": "B",
        },
        {
            "event_type": "POST_RESCUE_REENTRY_TRIGGERED",
            "event_timestamp": "2026-09-29T10:05:00+05:30",
            "direction": "BULLISH",
            "underlying_price": 105.0,
            "family": "B",
        },
    ]
    audit.write_text("".join(json.dumps(x) + "\n" for x in events))

    c._v621_observe_completed_minute(
        ts=datetime.fromisoformat("2026-09-29T10:06:00+05:30"),
        underlying=SimpleNamespace(high=134.0, low=118.0, close=124.0),
    )

    terminal = {
        "event_type": "STRUCTURAL_TERMINAL",
        "event_timestamp": "2026-09-29T10:07:00+05:30",
        "direction": "BULLISH",
        "underlying_price": 114.0,
        "family": "B",
    }
    with audit.open("a") as fh:
        fh.write(json.dumps(terminal) + "\n")

    c._v621_observe_completed_minute(
        ts=datetime.fromisoformat("2026-09-29T10:07:00+05:30"),
        underlying=SimpleNamespace(high=134.0, low=112.0, close=114.0),
    )

    rows = ledger.read_text().splitlines()
    assert len(rows) == 2
    assert "2026-09-29" in rows[1]
    assert ",114.0," in rows[1]
