from datetime import datetime
from pathlib import Path

import market_lab.hilega_directional_live_shadow_ui_v1 as ui
from market_lab.hilega_market_evidence_v1 import EvidenceJournalV1


def row(stage, payload, *, status="PASS"):
    return {
        "event_time": "2026-09-26T09:30:30+05:30",
        "checkpoint": payload.get("signal_bar") or payload.get("bar_timestamp"),
        "stage": stage,
        "status": status,
        "payload": payload,
    }


def test_operational_uses_latest_process_start_expiry_metadata(tmp_path, monkeypatch):
    root = tmp_path / "evidence"; root.mkdir()
    journal = EvidenceJournalV1(root / "2026-09-26.jsonl")
    journal.append("process_start", {"session_date": "2026-09-26"}, {"expiry": "2026-09-29", "expiry_source": "CONFIGURED_ENV"})
    journal.close()
    monkeypatch.setattr(ui, "EVIDENCE_ROOT", root)
    rows = [row("DIRECTIONAL_LIVE_BOOTSTRAP", {
        "session_date": "2026-09-26", "trade_owner": "NONE", "bullish_state": "PATH1_IDLE",
        "bearish_state": "BEARISH_PATH1_IDLE", "last_completed_bar": None,
        "historical_sessions_loaded": 31, "bars_replayed": 2325, "reconstructed": True,
        "recovered_checkpoint_count": 0,
        "option_restore": {"restored_active_count": 0, "restored_pending_exit_count": 0, "blocked_restore_count": 0, "restored_instrument_keys": []},
    })]
    got = ui._operational_payload(rows)
    assert got["session_date"] == "2026-09-26"
    assert got["option_expiry"] == "2026-09-29"
    assert got["option_expiry_source"] == "CONFIGURED_ENV"
    assert got["market_evidence"]["chain_ok"] is True
    assert got["restart_restore"]["restored_active_count"] == 0
    assert got["restart_restore"]["contract_master_lookup"] is False


def test_fast_status_defers_evidence_and_chain_verification(tmp_path, monkeypatch):
    root = tmp_path / "evidence"; root.mkdir()
    monkeypatch.setattr(ui, "EVIDENCE_ROOT", root)
    monkeypatch.setattr(ui, "STEP_AUDIT_PATH", tmp_path / "step-audit.jsonl")
    monkeypatch.setattr(ui, "_rows", lambda: [row("DIRECTIONAL_DECISION", {
        "bar_timestamp": "2026-09-26T09:30:00+05:30", "trade_owner_after": "NONE",
    })])
    monkeypatch.setattr(ui, "_latest_process_start", lambda: (_ for _ in ()).throw(AssertionError("full evidence read")))
    result = ui.status(fast=True)
    assert result["observation_only"] is True
    assert result["step_audit_chain_ok"] is None
    assert result["operational"]["market_evidence"]["chain_ok"] is None


def test_operational_surfaces_bootstrap_restore_identity(tmp_path, monkeypatch):
    root = tmp_path / "evidence"; root.mkdir()
    journal = EvidenceJournalV1(root / "2026-09-26.jsonl")
    journal.append("process_start", {"session_date": "2026-09-26"}, {"expiry": "2026-09-29", "expiry_source": "AUTO_UPSTOX_INSTRUMENT_SEARCH"})
    journal.close()
    monkeypatch.setattr(ui, "EVIDENCE_ROOT", root)
    signal = "2026-09-26T10:00:00+05:30"
    keys = ["AUDITED|-2", "AUDITED|-1", "AUDITED|0", "AUDITED|1", "AUDITED|2"]
    rows = [
        row("DIRECTIONAL_LIVE_BOOTSTRAP", {"session_date": "2026-09-26", "trade_owner": "BULLISH", "bullish_state": "BULLISH_ACTIVE", "bearish_state": "BEARISH_PATH1_IDLE", "last_completed_bar": signal, "reconstructed": True}),
        row("BULLISH_OPTION_SHADOW_BOOTSTRAP_RESTORE", {"signal_bar": signal, "status": "ACTIVE", "identity_source": "AUDITED_OPTION_SNAPSHOT", "reconstructed": True, "contract_master_lookup": False, "shadow_selected_instrument_keys": keys}, status="RESTORED_ACTIVE"),
    ]
    restore = ui._operational_payload(rows)["restart_restore"]
    assert restore["restored_active_count"] == 1
    assert restore["restored_pending_exit_count"] == 0
    assert restore["identity_source"] == "AUDITED_OPTION_SNAPSHOT"
    assert restore["contract_master_lookup"] is False
    assert restore["restored_instrument_keys"] == keys


def test_operational_distinguishes_worker_session_from_stale_state(tmp_path, monkeypatch):
    root = tmp_path / "evidence"; root.mkdir()
    journal = EvidenceJournalV1(root / "2026-09-26.jsonl")
    journal.append("process_start", {"session_date": "2026-09-26"}, {"expiry": "2026-09-29", "expiry_source": "CONFIGURED_ENV"})
    journal.close()
    monkeypatch.setattr(ui, "EVIDENCE_ROOT", root)
    rows = [row("DIRECTIONAL_LIVE_BOOTSTRAP", {"session_date": "2026-09-25", "trade_owner": "BULLISH", "bullish_state": "BULLISH_ACTIVE", "bearish_state": "BEARISH_PATH1_ARMED", "last_completed_bar": "2026-09-25T14:25:00+05:30"})]
    got = ui._operational_payload(rows)
    assert got["worker_session_date"] == "2026-09-26"
    assert got["directional_state_session_date"] == "2026-09-25"
    assert got["session_date"] == "2026-09-26"
    assert got["directional"]["bootstrap_present"] is False
    assert got["directional"]["trade_owner"] == "NONE"


def test_status_safety_contract_remains_observation_only(tmp_path, monkeypatch):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence"; evidence.mkdir()
    monkeypatch.setattr(ui, "STEP_AUDIT_PATH", audit)
    monkeypatch.setattr(ui, "EVIDENCE_ROOT", evidence)
    monkeypatch.setenv("LIVE_SHADOW_STRATEGY", "HILEGA_DIRECTIONAL_SHADOW_V1")
    got = ui.status()
    assert got["observation_only"] is True
    assert got["execution_enabled"] is False
    assert got["paper_order_enabled"] is False
    assert got["quantity"] is None
    assert got["operational"]["observation_only"] is True
    assert got["operational"]["execution_enabled"] is False


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 6, 9, 30, tzinfo=tz)


def test_previous_session_lock_is_not_returned_as_current_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "datetime", FixedDateTime)
    monkeypatch.setattr(ui, "STEP_AUDIT_PATH", tmp_path / "missing-step-audit.jsonl")
    monkeypatch.setattr(ui, "EVIDENCE_ROOT", tmp_path / "missing-evidence")
    monkeypatch.setattr(ui, "_rows", lambda: [row("DIRECTIONAL_SESSION_CUTOFF", {
        "bar_timestamp": "2026-10-05T14:55:00+05:30",
        "trade_owner_after": "NONE",
        "bullish_state": "SESSION_LOCKED",
        "bearish_state": "SESSION_LOCKED",
    }, status="PROCESSED")])

    result = ui.status(fast=True)

    assert result["current"]["session_date"] == "2026-10-06"
    assert result["current"]["state_available"] is False
    assert result["current"]["bullish_state"] is None
    assert result["current"]["bearish_state"] is None
    assert result["latest_state_session_date"] == "2026-10-05"
    assert result["latest_accepted_record"] is None


def test_trade_dashboard_excludes_previous_session_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "datetime", FixedDateTime)
    monkeypatch.setattr(ui, "_rows", lambda: [row("DIRECTIONAL_SESSION_CUTOFF", {
        "bar_timestamp": "2026-10-05T14:55:00+05:30",
    }, status="PROCESSED")])

    result = ui.trade_dashboard()

    assert result["trade_count"] == 0


def test_live_view_filters_audit_rows_to_current_session():
    source = (Path(__file__).parents[1] / "frontend/src/hilegaMilegaShadow.tsx").read_text(encoding="utf-8")
    assert "r.checkpoint.slice(0,10)===s.current.session_date" in source
    assert "status?.current.state_available===false" in source
