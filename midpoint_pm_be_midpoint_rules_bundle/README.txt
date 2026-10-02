MIDPOINT PM B/E MIDPOINT-FIRST RULES BUNDLE
===========================================

Placement:
  RB-ITOS-AI/midpoint_pm_be_midpoint_rules_bundle/

Install:
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_pm_be_midpoint_rules_bundle/install.py

Validate today's PM structure without changing live state:
  PYTHONPATH=backend:. python scripts/validate_midpoint_pm_e_session.py \
    --session-date 2026-09-30

The installer:
  - preserves the repository folder structure;
  - backs up overwritten targets under data/backups;
  - runs focused tests and git diff --check;
  - does not edit .env;
  - does not restart services;
  - does not enable PM live shadow;
  - does not send paper or live orders.
