Phase B recovery apply patch

Adds:
- backend/market_lab/hilega_directional_option_recovery_apply_v1.py
- tools/patch_hilega_directional_trade_dashboard_recovery_v1.py

This preserves the hash-chained ShadowStepAuditStoreV1 format, creates a backup before the first append, restores the backup if apply raises, and is idempotent by recovery_id.

Do NOT restart the Hilega worker yet.

INSTALL
  cd ~/RB-ITOS-AI
  unzip -o hilega_phase_b_apply_patch.zip -d ~/RB-ITOS-AI
  source .venv/bin/activate
  export PYTHONPATH=backend

PATCH DASHBOARD
  python tools/patch_hilega_directional_trade_dashboard_recovery_v1.py

COMPILE
  python -m py_compile \
    backend/market_lab/hilega_directional_option_recovery_apply_v1.py \
    backend/market_lab/hilega_directional_trade_dashboard_v1.py

VERIFY EXISTING TESTS
  python -m pytest \
    tests/test_hilega_directional_exact_entry_retry_v1.py -v

PRE-APPLY CHAIN CHECK
  python - <<'PY'
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
s=ShadowStepAuditStoreV1("data/live-observation/hilega-directional-v1/step-audit.jsonl")
print("VERIFY:", s.verify_chain())
print("ROWS:", len(s.read_all()))
PY

FIRST APPLY
  python -m market_lab.hilega_directional_option_recovery_apply_v1 \
    --session 2026-09-25 \
    --apply \
    --json-output data/historical-evidence/hilega-directional-option-recovery-apply-2026-09-25-v1.json

Expected first apply from the current baseline:
  status: APPLIED
  applied_count: 9
  skipped_count: 0
  audit_records_before: 160
  audit_records_after: 169
  audit_chain_valid: true

SECOND APPLY - IDEMPOTENCY
Run the same command again.
Expected:
  status: ALREADY_APPLIED
  applied_count: 0
  skipped_count: 9
  audit_records_after: 169

POST-APPLY VERIFY
  python - <<'PY'
import json
from pathlib import Path
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from market_lab.hilega_directional_trade_dashboard_v1 import project_directional_shadow_dashboard

p=Path("data/live-observation/hilega-directional-v1/step-audit.jsonl")
rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
store=ShadowStepAuditStoreV1(p)
print("CHAIN:", store.verify_chain())
print("AUDIT RECORDS:", len(rows))
recovery=[r for r in rows if str(r.get("stage","")).endswith("_OPTION_SHADOW_RECOVERY")]
print("RECOVERY RECORDS:", len(recovery))
print("RECOVERY IDS UNIQUE:", len({(r.get("payload") or {}).get("recovery_id") for r in recovery}))
d=project_directional_shadow_dashboard(rows)
print("TRADE COUNT:", d["trade_count"])
print("CLOSED:", d["complete_closed_count"])
print("INCOMPLETE:", d["incomplete_count"])
print("PENDING:", d["pending_exit_count"])
PY

Do not restart the worker after this. Next: bootstrap hardening and missing-intermediate-minute negative regression.
