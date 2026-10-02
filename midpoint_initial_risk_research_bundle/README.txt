MIDPOINT INITIAL-RISK RESEARCH V1
=================================

Place this directory directly under ~/RB-ITOS-AI and run:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_initial_risk_research_bundle/install.py

Then run development only:

First validate today's live session:

  PYTHONPATH=backend:. python scripts/validate_midpoint_live_session.py \
    --session-date 2026-09-30

Then run development only:

  PYTHONPATH=backend:. python scripts/research_midpoint_initial_risk_exits.py \
    --phase develop

Review:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-initial-risk-v1/development/elimination-matrix.csv

Do not run --phase validate-oos before a policy has been reviewed and locked.
The complete workflow and status checklist are in:

  docs/MIDPOINT_INITIAL_RISK_RESEARCH_CHECKLIST.md

Safety: research only. No service, .env, live audit, order, paper order,
quantity, or proved-runner exit is changed.
