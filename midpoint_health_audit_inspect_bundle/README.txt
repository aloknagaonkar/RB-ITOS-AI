MIDPOINT TRADE HEALTH — AUDIT INSPECT
=====================================

Copy this folder into the RB-ITOS-AI repository root, then run:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_health_audit_inspect_bundle/install.py
  ./scripts/restart.sh
  ./scripts/status.sh

What changes
------------
- Audit Inspect shows a dedicated Trade Health section for health events.
- It displays DI spread, combined edge, price momentum, futures/VWAP,
  directional volume, EMA 9/21, MACD, RSI14, scores, ADX and volume ratio.
- The main audit table combines Time with Session and NIFTY with points from
  entry. With the new Health column, the table has 10 compact columns.
- A Health column displays HEALTHY, UNHEALTHY, or UNAVAILABLE and the recorded
  core-support count. Non-health events display a dash; health is not carried
  forward from another minute.
- Raw evidence remains available.

Safety
------
- observation_only=true
- execution_enabled=false
- paper_order_enabled=false
- quantity=None
- No entry veto, authoritative exit, order, or quantity behavior is changed.

New extended evidence is recorded for health events created after restart.
Older audit rows continue to display whatever evidence they already contain.
