MIDPOINT T+5 LIVE OBSERVATION BUNDLE
===================================

Folder structure after installation
-----------------------------------
backend/market_lab/midpoint_strategy/
  entry_health_live_v1.py
  config.py
  workspace_contract.py
  live_shadow_v1.py
  live_shadow_ui.py
scripts/
  report_midpoint_t5_family_direction.py
tests/
  test_midpoint_t5_live_shadow_candidates.py

What it does
------------
At the exact completed entry+5 minute, an active trade that has not reached
+20 proof is evaluated using the frozen causal health features:
  directional DI spread, combined directional edge, and price momentum.

It records two independent parallel candidates:
  T5_TWO_OF_THREE_EXIT_CANDIDATE
  T5_COMBINED_EDGE_EXIT_CANDIDATE

It also records T5_HEALTH_CHECK, T5_PROVED_BYPASS, or
T5_HEALTH_UNAVAILABLE. Incomplete warm-up never triggers an exit candidate.

These events cannot close a trade, send an order, or change B/E/rearm/PM
management. Existing structural, DEGRADED, and NORMAL_B_PROVED paths remain
authoritative.

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python midpoint_t5_live_observation_bundle/install.py

Historical family/direction report (no restart required)
--------------------------------------------------------
PYTHONPATH=backend:. python scripts/report_midpoint_t5_family_direction.py

Enable for live observation
---------------------------
The defaults are enabled. Optional explicit .env values are:
MIDPOINT_T5_TWO_OF_THREE_CANDIDATE_ENABLED=true
MIDPOINT_T5_COMBINED_EDGE_CANDIDATE_ENABLED=true

After installation, restart once so the running worker loads the source:
./scripts/restart.sh
./scripts/status.sh

Verify
------
curl -fsS http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/status | \
python -c 'import json,sys; x=json.load(sys.stdin); m=x["workspace"]["management"]; print({k:m[k] for k in m if k.startswith("t5_")}); print("health",x.get("latest_t5_health_check")); print("2of3",x.get("latest_t5_two_of_three")); print("edge",x.get("latest_t5_combined_edge")); print("bypass",x.get("latest_t5_proved_bypass")); print("unavailable",x.get("latest_t5_unavailable")); print("safety",x["safety"])'
