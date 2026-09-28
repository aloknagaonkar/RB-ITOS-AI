MIDPOINT STRATEGY — M2 AUDITABLE FAMILY B RUNTIME

Prerequisite:
M1 files must already be present in the repo.

Copy this package over the repo preserving paths.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_m2_audit_smoke.py

Then:

python -m pytest tests/test_midpoint_m2_auditable_runtime.py -v

Expected smoke output includes PASS for:
- delayed B detector
- rejected confirmation audit
- B entry audit
- +20 / runner classification
- degraded / recovery
- rejected CAP20 check
- CAP20 rescue
- rejected re-entry check
- post-CAP20 re-entry
- safety on every audit row
- no order functionality

Review before staging.

Suggested explicit staging:

git add \
  backend/market_lab/midpoint_strategy/audit.py \
  backend/market_lab/midpoint_strategy/structure.py \
  backend/market_lab/midpoint_strategy/family_b_detector.py \
  backend/market_lab/midpoint_strategy/runtime.py \
  backend/market_lab/midpoint_strategy/replay.py \
  scripts/midpoint_m2_audit_smoke.py \
  tests/test_midpoint_m2_auditable_runtime.py \
  docs/MIDPOINT_STRATEGY_M2_AUDITABLE_RUNTIME.md

Do not use git add .
