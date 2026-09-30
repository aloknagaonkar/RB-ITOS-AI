MIDPOINT REPEATED B/E REARM LIVE SHADOW
=======================================

Install (does not restart services):

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_repeated_be_rearm_live_bundle/install.py

The installer sets:

  MIDPOINT_FAMILY_C_SHADOW_ENABLED=false
  MIDPOINT_BE_REARM_SHADOW_ENABLED=true

After PASS, restart using the repository script:

  ./scripts/restart.sh
  ./scripts/status.sh

Verify:

  curl -fsS http://127.0.0.1:8123/api/live-shadow/midpoint-strategy/status | \
  python -c 'import json,sys; x=json.load(sys.stdin); print(x["workspace"]["families"], x["safety"])'

Run today's exit diagnostic independently:

  PYTHONPATH=backend:. python \
    scripts/research_normal_b_tier1_classifier_exit.py

Repeated B/E is observation-only. The exit diagnostic does not change the
current live exit policy.
