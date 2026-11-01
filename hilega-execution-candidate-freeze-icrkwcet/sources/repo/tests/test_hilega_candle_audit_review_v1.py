from datetime import datetime, timedelta
import json

import pytest

from market_lab import hilega_candle_evidence_v1 as e
from market_lab.hilega_candle_audit_review_v1 import review
from market_lab.gateways import normalize_upstox_historical_candles
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from market_lab.domain import IST


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    monkeypatch.setenv("HILEGA_CANDLE_EVIDENCE_ROOT", str(root))
    start = datetime(2026, 10, 28, 9, 15, tzinfo=IST)
    decision = start + timedelta(minutes=5)
    body = {"status": "success", "data": {"candles": [
        [(start+timedelta(minutes=i)).isoformat(), 100, 102, 99, 101, 0]
        for i in range(5)
    ]}}
    rows = normalize_upstox_historical_candles(e.INSTRUMENT, start.date(), body)
    batch = e.capture(
        rows, body, start.date(),
        decision+timedelta(seconds=20), decision+timedelta(seconds=21),
    )
    journal = tmp_path / "audit.jsonl"
    payload = dict(
        strategy_id="HILEGA_V2_ALIGNMENT_DUAL_EXIT",
        reconstructed=False, execution_enabled=False, observation_only=True,
        decision_timestamp=decision.isoformat(),
        bar_timestamp=start.isoformat(),
        minute_timestamp=(decision-timedelta(minutes=1)).isoformat(),
        minute_ohlcv=dict(open=100, high=102, low=99, close=101),
        price_ema_frame=dict(open=100, high=102, low=99, close=101),
        candle_evidence=batch.candle_evidence,
        audit_payload_created_at=(decision+timedelta(seconds=22)).isoformat(),
    )
    return root, journal, start, decision, payload


def append(sample):
    root, journal, start, decision, payload = sample
    ShadowStepAuditStoreV1(journal).append(
        event_time=decision, checkpoint=decision-timedelta(minutes=1),
        stage="DIRECTIONAL_DECISION", status="PROCESSED", payload=payload,
    )
    return review(journal, root, start.date())


def test_linked_prices_and_timing_pass_without_source_changes(sample):
    root = sample[0]
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    report = append(sample)
    assert report["status"] == "PASS"
    assert report["linked_decisions"] == 1
    assert report["production_ready"] is False
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_wrong_recorded_close_fails(sample):
    sample[4]["price_ema_frame"]["close"] = 100
    report = append(sample)
    assert report["status"] == "FAILED"
    assert report["decisions"][0]["checks"]["five_minute_ohlc"] is False


def test_tampered_snapshot_fails(sample):
    ref = sample[4]["candle_evidence"]
    (sample[0] / (ref["snapshot_id"]+".json")).write_text("{}")
    assert append(sample)["status"] == "FAILED"


def test_unlinked_history_is_counted_not_cleared(sample):
    sample[4].pop("candle_evidence")
    report = append(sample)
    assert report["status"] == "WAITING"
    assert report["unlinked_decisions"] == 1


def test_future_candle_relative_to_receipt_fails(sample):
    sample[4]["decision_timestamp"] = (
        sample[3]+timedelta(minutes=5)
    ).isoformat()
    assert append(sample)["status"] == "FAILED"
