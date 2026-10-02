MIDPOINT PRE-ENTRY HEALTH OBSERVATION
=====================================

Folder structure
----------------
backend/market_lab/midpoint_strategy/
  entry_health_live_v1.py
  config.py
  workspace_contract.py
  live_shadow_v1.py
  live_shadow_ui.py
scripts/
  research_midpoint_entry_health_v1.py
  report_midpoint_preentry_health_outcomes.py
tests/
  test_midpoint_t5_live_shadow_candidates.py

Health definition
-----------------
Three causal directional inputs are evaluated:
  1. directional DI spread > 0
  2. combined directional edge > 0
  3. price momentum supports the intended direction

HEALTHY means at least two of three support the trade.
UNHEALTHY means fewer than two support it.
UNAVAILABLE is retained when indicator warm-up is incomplete.

The label is descriptive only. It cannot block an entry or close a trade.

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python midpoint_preentry_health_observation_bundle/install.py

Historical 490-session report
-----------------------------
# Regenerate features with the new exact T-1 preentry snapshot.
PYTHONPATH=backend:. python scripts/research_midpoint_entry_health_v1.py

# Produce health -> proof rate / points / PF / drawdown results.
PYTHONPATH=backend:. python scripts/report_midpoint_preentry_health_outcomes.py

Outputs
-------
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-preentry-health-outcomes-490-v1/
    report.json
    health-summary.csv
    oos-family-direction.csv
    trade-health-outcomes.csv

Live observation
----------------
Optional explicit environment gate:
MIDPOINT_PRE_ENTRY_HEALTH_OBSERVATION_ENABLED=true

Restart before market so the running worker loads the code:
./scripts/restart.sh
./scripts/status.sh

Verify
------
curl -fsS http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/status | \
python -c 'import json,sys; x=json.load(sys.stdin); print("enabled",x["workspace"]["management"]["pre_entry_health_observation_enabled"]); print("preentry",x.get("latest_pre_entry_health")); print("entry",x.get("latest_entry_health")); print("safety",x["safety"])'
