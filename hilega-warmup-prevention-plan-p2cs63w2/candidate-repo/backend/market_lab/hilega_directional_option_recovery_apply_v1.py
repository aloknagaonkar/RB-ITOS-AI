from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .domain import IST
from .hilega_directional_option_recovery_v1 import (
    DEFAULT_AUDIT,
    DEFAULT_EVIDENCE_ROOT,
    MODEL as RECOVERY_MODEL,
    build_report,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HILEGA_DIRECTIONAL_OPTION_RECOVERY_APPLY_V1"
RECOVERY_SUFFIX = "_OPTION_SHADOW_RECOVERY"


def recovery_id(direction: str, signal_bar: str) -> str:
    return f"{RECOVERY_MODEL}:{direction}:{signal_bar}"


def _existing_recovery_ids(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        stage = str(row.get("stage") or "")
        if not stage.endswith(RECOVERY_SUFFIX):
            continue
        payload = row.get("payload") or {}
        rid = payload.get("recovery_id")
        if isinstance(rid, str) and rid:
            out[rid] = row
    return out


def _payload_for_trade(trade: dict[str, Any]) -> dict[str, Any]:
    snap = dict(trade["recovered_snapshot"])
    rid = recovery_id(trade["direction"], trade["signal_bar"])
    return {
        **snap,
        "recovery_id": rid,
        "recovery_model": RECOVERY_MODEL,
        "recovery_apply_model": MODEL,
        "recovery_source": "RECORDED_MARKET_EVIDENCE",
        "reconstructed": True,
        "original_signal_bar": trade["signal_bar"],
        "original_entry_boundary": trade["entry_boundary"],
        "directional_exit_signal_bar": trade["exit_signal_bar"],
        "directional_exit_boundary": trade["exit_boundary"],
        "directional_exit_event": trade["exit_event"],
        "candidate_keys_verified": bool(trade.get("candidate_keys_verified")),
        "full_exact_path_verified": bool(trade.get("full_exact_path_verified")),
        "exact_exit_verified": bool(trade.get("exact_exit_verified")),
        "evidence_provenance": trade.get("evidence") or {},
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "option_selection_enabled": False,
        "quantity": None,
        "rupee_pnl_enabled": False,
    }


def apply_recovery(*, session: str, audit_path: Path, evidence_path: Path, backup_path: Path | None = None) -> dict[str, Any]:
    store = ShadowStepAuditStoreV1(audit_path)

    ok, issue = store.verify_chain()
    if not ok:
        raise ValueError(f"AUDIT_CHAIN_INVALID_BEFORE_APPLY:{issue}")

    report = build_report(session=session, audit_path=audit_path, evidence_path=evidence_path)
    if report.get("status") != "PASS" or int(report.get("blocked_count") or 0) != 0:
        raise ValueError(
            "RECOVERY_REPORT_NOT_PASS:"
            f"recoverable={report.get('recoverable_count')}:"
            f"blocked={report.get('blocked_count')}"
        )

    trades = list(report.get("trades") or [])
    if not trades:
        raise ValueError("NO_RECOVERABLE_TRADES")

    for trade in trades:
        if trade.get("status") != "RECOVERABLE":
            raise ValueError(f"NON_RECOVERABLE_TRADE_IN_PASS_REPORT:{trade.get('signal_bar')}")
        if (trade.get("recovered_snapshot") or {}).get("status") != "CLOSED":
            raise ValueError(f"RECOVERY_SNAPSHOT_NOT_CLOSED:{trade.get('signal_bar')}")

    before_rows = store.read_all()
    existing = _existing_recovery_ids(before_rows)
    planned: list[dict[str, Any]] = []
    skipped: list[str] = []

    for trade in trades:
        rid = recovery_id(trade["direction"], trade["signal_bar"])
        if rid in existing:
            payload = existing[rid].get("payload") or {}
            if payload.get("status") != "CLOSED":
                raise ValueError(f"EXISTING_RECOVERY_NOT_CLOSED:{rid}")
            skipped.append(rid)
        else:
            planned.append(trade)

    if not planned:
        return {
            "status": "ALREADY_APPLIED",
            "model": MODEL,
            "session_date": session,
            "planned_count": 0,
            "applied_count": 0,
            "skipped_count": len(skipped),
            "audit_records_before": len(before_rows),
            "audit_records_after": len(before_rows),
            "backup_path": None,
            "audit_chain_valid": True,
        }

    if backup_path is None:
        stamp = datetime.now(IST).strftime("%Y%m%d-%H%M%S")
        backup_path = audit_path.with_name(f"{audit_path.name}.pre-option-recovery-{stamp}.bak")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audit_path, backup_path)
    appended_ids: list[str] = []

    try:
        for trade in planned:
            rid = recovery_id(trade["direction"], trade["signal_bar"])
            store.append(
                event_time=datetime.now(IST),
                checkpoint=datetime.fromisoformat(trade["signal_bar"]).astimezone(IST),
                stage=f"{trade['direction']}{RECOVERY_SUFFIX}",
                status="PASS",
                payload=_payload_for_trade(trade),
                observation_id=rid,
            )
            appended_ids.append(rid)

        ok_after, issue_after = store.verify_chain()
        if not ok_after:
            raise RuntimeError(f"AUDIT_CHAIN_INVALID_AFTER_APPLY:{issue_after}")
    except Exception:
        shutil.copy2(backup_path, audit_path)
        raise

    after_rows = store.read_all()
    return {
        "status": "APPLIED",
        "model": MODEL,
        "session_date": session,
        "planned_count": len(planned),
        "applied_count": len(appended_ids),
        "skipped_count": len(skipped),
        "applied_recovery_ids": appended_ids,
        "audit_records_before": len(before_rows),
        "audit_records_after": len(after_rows),
        "backup_path": str(backup_path),
        "audit_chain_valid": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=MODEL)
    parser.add_argument("--session", required=True)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()

    evidence_path = args.evidence or (DEFAULT_EVIDENCE_ROOT / f"{args.session}.jsonl")
    if not args.audit.exists():
        raise SystemExit(f"AUDIT_NOT_FOUND:{args.audit}")
    if not evidence_path.exists():
        raise SystemExit(f"EVIDENCE_NOT_FOUND:{evidence_path}")

    result = apply_recovery(
        session=args.session,
        audit_path=args.audit,
        evidence_path=evidence_path,
        backup_path=args.backup,
    )
    print(json.dumps(result, indent=2))

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
