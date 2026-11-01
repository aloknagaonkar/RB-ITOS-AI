"""Offline evidence tests: temporary files and mocked GET only."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from market_lab import hilega_candle_evidence_v1 as e
from market_lab.domain import IST
from market_lab.gateways import normalize_upstox_historical_candles
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
from market_lab.hilega_alignment_dual_exit_live_v1 import HilegaAlignmentDualExitLiveCoordinator
from market_lab.hilega_wma_gap_live_v2 import HilegaWmaGapLiveCoordinatorV2


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv(e.FLAG, "1")
    monkeypatch.setenv("HILEGA_CANDLE_EVIDENCE_ROOT", str(tmp_path / "inputs"))
    return tmp_path / "inputs"


def body():
    return {"status": "success", "data": {"candles": [
        ["2026-10-28T10:59:00+05:30", 100, 102, 99, 101, 0]
    ]}}


def batch():
    start = datetime(2026, 10, 28, 11, tzinfo=IST)
    rows = normalize_upstox_historical_candles(e.INSTRUMENT, start.date(), body())
    return e.capture(rows, body(), start.date(), start, start+timedelta(seconds=1))


def test_source_links_saved_response(configured):
    calls = []
    source = object.__new__(UpstoxLiveShadowSourcesV1)
    def get(path):
        calls.append(path)
        return body()
    source.gateway = SimpleNamespace(_get=get)
    rows = source.nifty_intraday_1m(now=datetime(2026, 10, 28, 11, tzinfo=IST))
    ref = e.verify(rows)
    assert len(calls) == 1
    assert (configured / (ref["snapshot_id"] + ".json")).is_file()
    assert configured.stat().st_mode & 0o077 == 0


def test_tampered_snapshot_rejected(configured):
    rows = batch()
    (configured / (rows.candle_evidence["snapshot_id"] + ".json")).write_text("{}")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        e.verify(rows)


def test_changed_rows_rejected(configured):
    rows = batch()
    rows.clear()
    with pytest.raises(ValueError, match="ROWS_CHANGED"):
        e.verify(rows)


def test_missing_evidence_stops_before_consume(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(HilegaWmaGapLiveCoordinatorV2, "_consume",
                        lambda *a, **kw: calls.append(True))
    owner = object.__new__(HilegaAlignmentDualExitLiveCoordinator)
    with pytest.raises(ValueError, match="BATCH_REQUIRED"):
        owner._consume([], datetime.now(IST), recovered=False)
    assert calls == []


def test_context_cleared_on_failure(configured, monkeypatch):
    rows = batch()
    owner = object.__new__(HilegaAlignmentDualExitLiveCoordinator)
    observed = []
    def consume(self, *args, **kwargs):
        observed.append(e.audit_fields(self))
        raise RuntimeError("synthetic")
    monkeypatch.setattr(HilegaWmaGapLiveCoordinatorV2, "_consume", consume)
    with pytest.raises(RuntimeError):
        owner._consume(rows, datetime.now(IST), recovered=False)
    assert observed[0]["candle_evidence"] == rows.candle_evidence
    assert e.audit_fields(owner) == {}


def test_cutoff_links_its_input(configured, monkeypatch):
    owner = object.__new__(HilegaAlignmentDualExitLiveCoordinator)
    rows = batch()
    monkeypatch.setattr(
        HilegaAlignmentDualExitLiveCoordinator, "_process_cutoff_from_rows",
        lambda self, now, *, intraday: e.audit_fields(self),
    )
    result = owner.process_cutoff(datetime.now(IST), intraday=rows)
    assert result["candle_evidence"] == rows.candle_evidence
    assert e.audit_fields(owner) == {}


def test_disabled_source_remains_plain_list(configured, monkeypatch):
    monkeypatch.setenv(e.FLAG, "0")
    source = object.__new__(UpstoxLiveShadowSourcesV1)
    source.gateway = SimpleNamespace(_get=lambda path: body())
    rows = source.nifty_intraday_1m(now=datetime(2026, 10, 28, 11, tzinfo=IST))
    assert type(rows) is list
    assert not configured.exists()


def test_recording_wrapper_preserves_link(configured):
    from market_lab.hilega_market_evidence_v1 import EvidenceJournalV1, RecordingHilegaSourcesV1
    rows = batch()
    journal = EvidenceJournalV1(configured / "tape.jsonl")
    wrapped = RecordingHilegaSourcesV1(
        SimpleNamespace(nifty_intraday_1m=lambda **kw: rows), journal
    )
    try:
        assert wrapped.nifty_intraday_1m(now=datetime.now(IST)) is rows
        assert e.verify(rows) == rows.candle_evidence
    finally:
        journal.close()
