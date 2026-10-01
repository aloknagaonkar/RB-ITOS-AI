MIDPOINT FAMILY A + CONTINUOUS HEALTH — OBSERVATION ONLY

Copy this complete folder into the RB-ITOS-AI repository root:

RB-ITOS-AI/
├── midpoint_a_continuous_health_bundle/
│   ├── install.py
│   ├── README.txt
│   └── files/
│       ├── backend/market_lab/midpoint_strategy/
│       ├── frontend/src/
│       ├── scripts/
│       ├── tests/
│       └── docs/
├── backend/
├── frontend/
├── scripts/
└── tests/

The installer validates source and frontend first. Only after validation passes
does it set these observation gates in .env:

MIDPOINT_FAMILY_A_SHADOW_ENABLED=true
MIDPOINT_CONTINUOUS_HEALTH_EXIT_CANDIDATE_ENABLED=true

It does not restart services.

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_a_continuous_health_bundle/install.py

Restart after PASS:

  ./scripts/restart.sh
  ./scripts/status.sh

Run fixed 490-session comparison plus a temporary broker replay and immutable
live-audit summary for 2026-10-01:

  PYTHONPATH=backend:. python \
    scripts/backtest_midpoint_a_continuous_health.py \
    --live-session-date 2026-10-01

Outputs:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-a-continuous-health-490-v1/report.json

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-a-continuous-health-490-v1/trade-policy-comparison.csv

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-a-continuous-health-490-v1/today-trade-policy-comparison.csv

Verify live gates:

  curl -fsS http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/status | \
  python -c '
import json,sys
x=json.load(sys.stdin)
print("A:",x["workspace"]["families"]["A"])
print("continuous health:",x["workspace"]["management"]["continuous_health_exit_candidate_enabled"])
print("latest health:",x.get("latest_continuous_health"))
print("immediate:",x.get("latest_health_immediate_exit"))
print("two-close:",x.get("latest_health_two_close_exit"))
print("safety:",x["safety"])
'

No execution, paper order, quantity, or order transmission is enabled.
