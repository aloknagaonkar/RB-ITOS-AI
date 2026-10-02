MIDPOINT HEALTH TIMELINE PRESENTATION FIX

Folder placement:

  ~/RB-ITOS-AI/
  ├── midpoint_health_timeline_fix_bundle/
  │   ├── install.py
  │   └── files/
  │       ├── backend/market_lab/midpoint_strategy/live_shadow_ui.py
  │       ├── frontend/src/midpointStrategyShadow.tsx
  │       └── tests/test_midpoint_health_audit_inspect.py
  ├── backend/
  ├── frontend/
  └── tests/

Run:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_health_timeline_fix_bundle/install.py

After PASS:

  ./scripts/restart.sh
  ./scripts/status.sh

The installer does not restart a service. It changes presentation projection
only. Every active-trade signal receives causal health for the same reference.
The single Inspect decision action includes its matching health evidence.
Immutable health and strategy audit events remain untouched.
