MIDPOINT C + PM_E SHARED SHADOW BUNDLE
======================================

Copy this entire folder directly under ~/RB-ITOS-AI, preserving its name and
the files/ directory. The installer validates source and frontend but does not
restart any service and does not enable C or PM_E.

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_c_pm_e_shared_shadow_bundle/install.py

Mandatory historical gate before live activation:

  PYTHONPATH=backend:. python \
    scripts/midpoint_c_pm_e_shared_lifecycle_validation.py

Review:

  python -m json.tool \
    data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-c-pm-e-shared-lifecycle-v1/report.json

The report must show:
  - no_future_leakage_checks = PASS
  - D = false
  - execution_enabled = false
  - paper_order_enabled = false
  - quantity = null
  - harmed counts reviewed for C and PM_E

Only after accepting the historical report, enable observation-only gates:

  sed -i '/^MIDPOINT_FAMILY_C_SHADOW_ENABLED=/d' .env
  sed -i '/^MIDPOINT_PM_E_SHADOW_ENABLED=/d' .env
  printf '%s\n' \
    'MIDPOINT_FAMILY_C_SHADOW_ENABLED=1' \
    'MIDPOINT_PM_E_SHADOW_ENABLED=1' >> .env

Then restart once:

  ./scripts/restart.sh
  ./scripts/status.sh

Verify actual worker/API configuration:

  curl -fsS \
    http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/status | \
  python -c 'import json,sys; x=json.load(sys.stdin); print(x["workspace"]["families"]); print(x["workspace"]["management"]); print(x["safety"])'

Expected family gates:
  B true, E true, C true, D false, PM_E true

Semantics:
  C      = origin B/E touched its original midpoint, origin structurally
           closed, then a strictly later completed close freshly broke the
           original boundary and passed B/E ownership qualification.
  PM_E   = exact 12:45-13:14 reference, first false boundary break, completed
           midpoint recross, later fresh opposite boundary close, E ownership.
  Shared = +20 intrabar proof, exact proof+10 classifier, exclusive routing:
           NORMAL_B -> three-tier candidate; RUNNER_STRENGTHENING -> first
           DEGRADED_STARTED-close candidate; otherwise structural baseline.

All new exits are candidate valuations only. They cannot close the baseline
lifecycle, send orders, set quantity, or re-enter a candidate trade.
