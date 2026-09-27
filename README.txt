B FAMILY — POST-08-SEP UNSEEN VALIDATION READINESS AUDIT V9.1

Fixes V9 classify() bug:
  p.name -> Path(p["path"]).name

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_08sep_readiness_audit_v9_1.py \
  | tee /tmp/b-family-post-08sep-readiness-audit-v9-1.txt

Research/readiness only. No strategy/runtime changes.
