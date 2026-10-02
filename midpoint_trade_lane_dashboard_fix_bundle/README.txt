MIDPOINT TRADE-LANE DASHBOARD FIX
=================================

Copy this folder directly into ~/RB-ITOS-AI, then run:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_trade_lane_dashboard_fix_bundle/install.py
  ./scripts/restart.sh
  ./scripts/status.sh

What changes
------------
- API projects one selected trade lane using session + family + direction +
  reference, with a separate generation after each terminal/rearm.
- Dashboard summary, lifecycle, health, active trade and exit cards all use
  that same lane.
- Closed views say "Latest completed trade" instead of "Current active rule".
- Parallel A, canonical B/E, repeated B/E and PM evidence cannot mix.
- Historical Replay receives the same correction through its status payload.

What does not change
--------------------
- Strategy entry or exit decisions
- Immutable audit records
- Health calculations
- Live or paper execution (both remain disabled)
- Quantity (remains None)
