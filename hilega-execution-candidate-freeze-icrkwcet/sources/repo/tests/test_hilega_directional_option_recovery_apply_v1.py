from datetime import datetime, timezone
from pathlib import Path

import pytest

import market_lab.hilega_directional_option_recovery_apply_v1 as apply_mod
import market_lab.hilega_directional_option_recovery_v1 as recovery_mod
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


SESSION = "2026-09-25"


def _dt(hour: int, minute: int) -> datetime:
    return datetime(
        2026, 9, 25, hour, minute,
        tzinfo=timezone.utc,
    )


def _seed_valid_audit(path: Path) -> ShadowStepAuditStoreV1:
    store = ShadowStepAuditStoreV1(path)
    store.append(
        event_time=_dt(9, 20),
        checkpoint=_dt(9, 15),
        stage="DIRECTIONAL_DECISION",
        status="PROCESSED",
        payload={"seed": True},
    )
    return store


def _trade(
    direction: str = "BULLISH",
    signal_bar: str = "2026-09-25T10:05:00+05:30",
) -> dict:
    return {
        "status": "RECOVERABLE",
        "direction": direction,
        "signal_bar": signal_bar,
        "recovered_snapshot": {
            "status": "CLOSED",
        },
    }


def _pass_report(trades: list[dict]) -> dict:
    return {
        "status": "PASS",
        "session_date": SESSION,
        "recoverable_count": len(trades),
        "blocked_count": 0,
        "trades": trades,
    }


def _closed_payload(trade: dict) -> dict:
    rid = apply_mod.recovery_id(
        trade["direction"],
        trade["signal_bar"],
    )
    return {
        "status": "CLOSED",
        "direction": trade["direction"],
        "signal_bar": trade["signal_bar"],
        "recovery_id": rid,
        "reconstructed": True,
    }


def test_build_report_dry_run_does_not_mutate_audit(
    tmp_path,
    monkeypatch,
):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence.jsonl"

    audit.write_text('{"seed": true}\n')
    evidence.write_text("")

    before = audit.read_bytes()

    monkeypatch.setattr(
        recovery_mod,
        "_unresolved_trades",
        lambda *, rows, session: [{"id": "T1"}],
    )
    monkeypatch.setattr(
        recovery_mod,
        "EvidenceOptionStore",
        lambda path: object(),
    )
    monkeypatch.setattr(
        recovery_mod,
        "_recover_trade",
        lambda *, trade, evidence: {
            "status": "RECOVERABLE",
            "direction": "BULLISH",
            "signal_bar": "2026-09-25T10:05:00+05:30",
        },
    )

    result = recovery_mod.build_report(
        session=SESSION,
        audit_path=audit,
        evidence_path=evidence,
    )

    after = audit.read_bytes()

    assert result["status"] == "PASS"
    assert result["mode"] == "DRY_RUN"
    assert result["audit_mutated"] is False
    assert result["recoverable_count"] == 1
    assert result["blocked_count"] == 0
    assert after == before


def test_first_apply_then_second_apply_is_idempotent(
    tmp_path,
    monkeypatch,
):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    backup = tmp_path / "audit.bak"

    store = _seed_valid_audit(audit)
    evidence.write_text("")

    trade = _trade()

    monkeypatch.setattr(
        apply_mod,
        "build_report",
        lambda **kwargs: _pass_report([trade]),
    )
    monkeypatch.setattr(
        apply_mod,
        "_payload_for_trade",
        _closed_payload,
    )

    first = apply_mod.apply_recovery(
        session=SESSION,
        audit_path=audit,
        evidence_path=evidence,
        backup_path=backup,
    )

    assert first["status"] == "APPLIED"
    assert first["planned_count"] == 1
    assert first["applied_count"] == 1
    assert first["skipped_count"] == 0
    assert first["audit_records_before"] == 1
    assert first["audit_records_after"] == 2
    assert first["audit_chain_valid"] is True
    assert backup.is_file()

    ok, issue = store.verify_chain()
    assert ok is True
    assert issue is None

    rows_after_first = store.read_all()
    assert len(rows_after_first) == 2

    rid = apply_mod.recovery_id(
        trade["direction"],
        trade["signal_bar"],
    )

    assert rows_after_first[-1]["observation_id"] == rid
    assert rows_after_first[-1]["payload"]["status"] == "CLOSED"

    bytes_after_first = audit.read_bytes()

    second = apply_mod.apply_recovery(
        session=SESSION,
        audit_path=audit,
        evidence_path=evidence,
        backup_path=tmp_path / "should-not-be-created.bak",
    )

    assert second["status"] == "ALREADY_APPLIED"
    assert second["planned_count"] == 0
    assert second["applied_count"] == 0
    assert second["skipped_count"] == 1
    assert second["audit_records_before"] == 2
    assert second["audit_records_after"] == 2
    assert second["backup_path"] is None
    assert second["audit_chain_valid"] is True

    assert audit.read_bytes() == bytes_after_first


def test_partial_existing_recovery_applies_only_missing_trade(
    tmp_path,
    monkeypatch,
):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    backup = tmp_path / "partial.bak"

    store = _seed_valid_audit(audit)
    evidence.write_text("")

    trade1 = _trade(
        "BULLISH",
        "2026-09-25T10:05:00+05:30",
    )
    trade2 = _trade(
        "BEARISH",
        "2026-09-25T12:40:00+05:30",
    )

    rid1 = apply_mod.recovery_id(
        trade1["direction"],
        trade1["signal_bar"],
    )

    store.append(
        event_time=_dt(10, 10),
        checkpoint=datetime.fromisoformat(
            trade1["signal_bar"]
        ),
        stage="BULLISH_OPTION_SHADOW_RECOVERY",
        status="PASS",
        payload=_closed_payload(trade1),
        observation_id=rid1,
    )

    before_count = len(store.read_all())

    monkeypatch.setattr(
        apply_mod,
        "build_report",
        lambda **kwargs: _pass_report(
            [trade1, trade2]
        ),
    )
    monkeypatch.setattr(
        apply_mod,
        "_payload_for_trade",
        _closed_payload,
    )

    result = apply_mod.apply_recovery(
        session=SESSION,
        audit_path=audit,
        evidence_path=evidence,
        backup_path=backup,
    )

    assert result["status"] == "APPLIED"
    assert result["planned_count"] == 1
    assert result["applied_count"] == 1
    assert result["skipped_count"] == 1
    assert result["audit_records_before"] == before_count
    assert result["audit_records_after"] == before_count + 1

    ok, issue = store.verify_chain()
    assert ok is True
    assert issue is None

    recovery_ids = [
        row.get("observation_id")
        for row in store.read_all()
        if row.get("observation_id")
    ]

    assert recovery_ids.count(rid1) == 1

    rid2 = apply_mod.recovery_id(
        trade2["direction"],
        trade2["signal_bar"],
    )
    assert recovery_ids.count(rid2) == 1


def test_conflicting_existing_recovery_fails_closed(
    tmp_path,
    monkeypatch,
):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence.jsonl"

    store = _seed_valid_audit(audit)
    evidence.write_text("")

    trade = _trade()

    rid = apply_mod.recovery_id(
        trade["direction"],
        trade["signal_bar"],
    )

    store.append(
        event_time=_dt(10, 10),
        checkpoint=datetime.fromisoformat(
            trade["signal_bar"]
        ),
        stage="BULLISH_OPTION_SHADOW_RECOVERY",
        status="PASS",
        payload={
            **_closed_payload(trade),
            "status": "ACTIVE",
        },
        observation_id=rid,
    )

    before = audit.read_bytes()

    monkeypatch.setattr(
        apply_mod,
        "build_report",
        lambda **kwargs: _pass_report([trade]),
    )

    with pytest.raises(
        ValueError,
        match="EXISTING_RECOVERY_NOT_CLOSED",
    ):
        apply_mod.apply_recovery(
            session=SESSION,
            audit_path=audit,
            evidence_path=evidence,
        )

    assert audit.read_bytes() == before

    ok, issue = store.verify_chain()
    assert ok is True
    assert issue is None


def test_apply_failure_restores_backup_exactly(
    tmp_path,
    monkeypatch,
):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    backup = tmp_path / "rollback.bak"

    store = _seed_valid_audit(audit)
    evidence.write_text("")

    trade1 = _trade(
        "BULLISH",
        "2026-09-25T10:05:00+05:30",
    )
    trade2 = _trade(
        "BEARISH",
        "2026-09-25T12:40:00+05:30",
    )

    monkeypatch.setattr(
        apply_mod,
        "build_report",
        lambda **kwargs: _pass_report(
            [trade1, trade2]
        ),
    )
    monkeypatch.setattr(
        apply_mod,
        "_payload_for_trade",
        _closed_payload,
    )

    original_bytes = audit.read_bytes()

    original_append = (
        apply_mod.ShadowStepAuditStoreV1.append
    )
    calls = {"count": 0}

    def failing_append(self, **kwargs):
        calls["count"] += 1

        if calls["count"] == 2:
            raise RuntimeError(
                "SIMULATED_SECOND_APPEND_FAILURE"
            )

        return original_append(self, **kwargs)

    monkeypatch.setattr(
        apply_mod.ShadowStepAuditStoreV1,
        "append",
        failing_append,
    )

    with pytest.raises(
        RuntimeError,
        match="SIMULATED_SECOND_APPEND_FAILURE",
    ):
        apply_mod.apply_recovery(
            session=SESSION,
            audit_path=audit,
            evidence_path=evidence,
            backup_path=backup,
        )

    assert calls["count"] == 2
    assert backup.is_file()

    # Transaction-style rollback must restore the audit
    # byte-for-byte to its pre-apply state.
    assert audit.read_bytes() == original_bytes
    assert backup.read_bytes() == original_bytes

    restored = ShadowStepAuditStoreV1(audit)
    ok, issue = restored.verify_chain()

    assert ok is True
    assert issue is None
    assert len(restored.read_all()) == 1


def test_invalid_audit_chain_is_rejected_before_apply(
    tmp_path,
    monkeypatch,
):
    audit = tmp_path / "step-audit.jsonl"
    evidence = tmp_path / "evidence.jsonl"

    _seed_valid_audit(audit)
    evidence.write_text("")

    # Corrupt immutable historical content.
    text = audit.read_text()
    audit.write_text(text.replace(
        '"seed": true',
        '"seed": false',
    ))

    called = {"report": False}

    def should_not_run(**kwargs):
        called["report"] = True
        return _pass_report([_trade()])

    monkeypatch.setattr(
        apply_mod,
        "build_report",
        should_not_run,
    )

    with pytest.raises(
        ValueError,
        match="AUDIT_CHAIN_INVALID_BEFORE_APPLY",
    ):
        apply_mod.apply_recovery(
            session=SESSION,
            audit_path=audit,
            evidence_path=evidence,
        )

    assert called["report"] is False
