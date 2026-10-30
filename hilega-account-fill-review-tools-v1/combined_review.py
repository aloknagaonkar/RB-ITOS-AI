
"""Combined diagnostic evidence; no execution or ownership authority."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def need(ok, reason):
    if not ok:
        raise ValueError(reason)

def now():
    return datetime.now(timezone.utc).isoformat()

def combine(audit, account, windows):
    need(audit.get("model") == "HILEGA_RISK_EVIDENCE_AUDIT_V1",
         "UNEXPECTED_LOCAL_AUDIT")
    need(audit.get("status") == "BLOCKED_EVIDENCE_GAPS",
         "UNEXPECTED_LOCAL_AUDIT_STATUS")
    need(account.get("model") == "HILEGA_ACCOUNT_FILL_REFERENCE_REVIEW_V1",
         "UNEXPECTED_ACCOUNT_REVIEW")
    need(account.get("status") == "REVIEW_COMPLETE_PRODUCTION_STILL_BLOCKED",
         "ACCOUNT_REVIEW_INCOMPLETE")
    need(account.get("account_identity_and_local_signature_verified") is True,
         "ACCOUNT_IDENTITY_NOT_VERIFIED")
    need(audit.get("account_scope_matches_local_pin") is True,
         "LOCAL_ACCOUNT_SCOPE_NOT_VERIFIED")
    for report in (audit, account):
        for flag in (
            "production_ready", "production_execution_enabled",
            "entry_permission", "orders_sent", "database_modified",
            "controller_changed", "reservation_release_permission",
        ):
            need(report.get(flag) is False, "UNEXPECTED_AUTHORITY_OR_MUTATION")
    need(isinstance(audit.get("gaps"), list), "AUDIT_GAPS_MISSING")
    return dict(
        model="HILEGA_COMBINED_EVIDENCE_REVIEW_V1",
        status="BLOCKED_RISK_INTEGRATION_PENDING",
        generated_at=now(),
        collection_windows=windows,
        collection_windows_are_not_broker_observation_timestamps=True,
        evidence_sources_atomic=False,
        common_capture_or_transaction_verified=False,
        local_audit=audit,
        account_review=account,
        unresolved_local_audit_gaps=list(audit["gaps"]),
        interpretation={
            "fresh_account_review_completed": True,
            "local_audit_assessed_that_account_capture": False,
            "application_hold_to_current_fill_link_verified": False,
            "empty_history_is_verified_zero_strategy_pnl": False,
        },
        strategy_ownership_verified=False,
        fees_complete=False,
        realized_net_pnl=None,
        open_net_pnl=None,
        production_daily_stop_integrated=False,
        risk_gate_input_ready=False,
        database_modified=False,
        controller_changed=False,
        entry_permission=False,
        reservation_release_permission=False,
        orders_sent=False,
        production_execution_enabled=False,
        production_ready=False,
    )

def run():
    python = ROOT / ".venv/bin/python"
    commands = (
        ("local_audit",
         ROOT / "hilega-risk-evidence-audit-tools-v1/risk_evidence_audit.py",
         ["check"]),
        ("account_review",
         ROOT / "hilega-account-fill-review-tools-v1/review.py",
         ["--capture-account"]),
    )
    reports, windows = {}, {}
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend") + ":" + str(ROOT)
    for name, script, arguments in commands:
        need(script.is_file() and not script.is_symlink(),
             "REGULAR_REVIEW_SCRIPT_REQUIRED")
        started = now()
        result = subprocess.run(
            [str(python), str(script), *arguments],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        ended = now()
        need(result.returncode == 0, name.upper() + "_FAILED")
        reports[name] = json.loads(result.stdout)
        windows[name] = dict(started_at=started, completed_at=ended)
    print(json.dumps(combine(
        reports["local_audit"], reports["account_review"], windows
    ), indent=2))

if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        message = str(exc)
        import re
        print(json.dumps(dict(
            status="STOPPED_FOR_REVIEW",
            error_type=type(exc).__name__,
            reason=message if re.fullmatch(
                r"[A-Z][A-Z0-9_]{0,179}", message
            ) else "NON_PUBLIC_ERROR_SUPPRESSED",
            production_ready=False,
            production_execution_enabled=False,
        )))
        raise SystemExit(1)
