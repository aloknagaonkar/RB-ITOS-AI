MIDPOINT CONTINUOUS DUAL-DIRECTION HEALTH
=========================================

Folder structure
----------------
midpoint_continuous_dual_health_bundle/
  install.py
  README.txt
  files/
    backend/market_lab/midpoint_strategy/live_shadow_v1.py
    backend/market_lab/midpoint_strategy/live_shadow_ui.py
    frontend/src/midpointStrategyShadow.tsx
    frontend/src/midpointStrategyShadow.css
    tests/test_midpoint_continuous_system_health.py
    tests/test_midpoint_trade_lane_dashboard.py
    tests/test_midpoint_active_rule_health_ui.py

Install
-------
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_continuous_dual_health_bundle/install.py
  ./scripts/restart.sh
  ./scripts/status.sh

Behavior
--------
- Recomputes BULLISH and BEARISH health for every completed common NIFTY and
  futures one-minute candle, whether or not an entry signal exists.
- Publishes one replaceable runtime heartbeat file; immutable strategy audit is
  not enlarged or changed.
- UI polls normally and shows system-running/stale, candle timestamp, NIFTY,
  futures/VWAP, both 3-vote health scores, precision and community evidence.
- Active-trade health remains separately tied to its exact trade lane.
- Health remains descriptive observation only and cannot create an entry,
  exit, paper order, live order or quantity.
