
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

from market_lab import hilega_candle_evidence_v1 as evidence
from market_lab import hilega_alignment_dual_exit_live_v1 as live
from market_lab import hilega_manual_exit_strategy_v1 as manual
from market_lab.domain import IST
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1


def test_source_snapshot_is_linked_to_real_decision_journal(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    monkeypatch.setenv(evidence.FLAG, "1")
    monkeypatch.setenv("HILEGA_CANDLE_EVIDENCE_ROOT", str(root))

    start = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    processing_time = start + timedelta(minutes=5, seconds=30)
    body = {"status": "success", "data": {"candles": [
        [(start + timedelta(minutes=i)).isoformat(),
         100.0, 101.0, 99.0, 100.0, 0]
        for i in range(5)
    ]}}
    requests = []

    def get(endpoint):
        requests.append(endpoint)
        return body

    source = object.__new__(UpstoxLiveShadowSourcesV1)
    source.gateway = SimpleNamespace(_get=get)
    rows = source.nifty_intraday_1m(now=processing_time)
    reference = evidence.verify(rows)

    coordinator = live.HilegaAlignmentDualExitLiveCoordinator(
        market_sources=source,
        option_expiry=None,
        step_audit_path=tmp_path / "steps.jsonl",
        health_path=tmp_path / "health.jsonl",
        cache_root=tmp_path / "unused-cache",
    )

    decision = SimpleNamespace(
        trade_owner_before="NONE", trade_owner_after="NONE",
        bullish_state="IDLE", bearish_state="IDLE",
        bullish_armed=False, bearish_armed=False,
        accepted_events=(), suppressed_events=(), note="SYNTHETIC_POLICY",
    )
    monkeypatch.setattr(coordinator, "_decision", lambda *a, **kw: decision)
    monkeypatch.setattr(manual, "apply_manual_control", lambda *a, **kw: False)
    monkeypatch.setattr(live, "confirmation_reference", lambda *a, **kw: None)
    evaluated = []

    def evaluate(canonical, gate, bar, reference, frames, manual_block):
        evaluated.append(bar)
        return {
            "decision": None, "current": None,
            "entries": [], "exits": [], "checks": [], "setups": [],
            "exit_validation": None, "pending_switches": [],
            "policy_events": [],
            "frame": {
                "candle_label": bar.ts.isoformat(),
                "available_at": (bar.ts + timedelta(minutes=5)).isoformat(),
                "close": bar.close,
            },
        }

    monkeypatch.setattr(live, "advance_boundary", evaluate)

    # Real _consume, _advance, _audit and journal append remain in use.
    coordinator._consume(rows, processing_time, recovered=False)

    assert len(requests) == 1
    assert len(evaluated) == 1
    assert coordinator.step_audit.verify_chain() == (True, None)

    records = coordinator.step_audit.read_all()
    decisions = [r for r in records if r["stage"] == "DIRECTIONAL_DECISION"]
    assert len(decisions) == 1
    record = decisions[0]
    payload = record["payload"]

    assert record["status"] == "PROCESSED"
    assert payload["execution_enabled"] is False
    assert payload["accepted_events"] == []
    assert payload["candle_evidence"] == reference
    assert payload["decision_timestamp"] == (
        start + timedelta(minutes=5)
    ).isoformat()
    assert payload["minute_timestamp"] == (
        start + timedelta(minutes=4)
    ).isoformat()

    created = datetime.fromisoformat(payload["audit_payload_created_at"])
    received = datetime.fromisoformat(reference["response_received_at"])
    assert created >= received

    snapshot_path = root / (reference["snapshot_id"] + ".json")
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["response"] == body
    assert snapshot["response_received_at"] == reference["response_received_at"]

    # Context must not leak into later unrelated audit calls.
    assert evidence.audit_fields(coordinator) == {}

    # An immutable snapshot change is detected before another consumption.
    saved_cursor = coordinator._last_minute
    saved_journal = (tmp_path / "steps.jsonl").read_bytes()
    snapshot_path.write_text("{}")

    import pytest
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        coordinator._consume(rows, processing_time, recovered=False)

    assert coordinator._last_minute == saved_cursor
    assert (tmp_path / "steps.jsonl").read_bytes() == saved_journal
