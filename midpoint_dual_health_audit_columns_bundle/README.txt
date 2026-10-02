MIDPOINT DUAL-HEALTH AUDIT COLUMNS
=================================

Install
-------
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_dual_health_audit_columns_bundle/install.py
  ./scripts/restart.sh
  ./scripts/status.sh

UI result
---------
The Midpoint candle-by-candle decision audit contains separate columns:

  Bullish health | Bearish health

Each displays HEALTHY / UNHEALTHY / UNAVAILABLE and the independent core
support score out of three. Both values are calculated from the same completed
one-minute candle, so no future health is copied into an earlier decision.

New live evidence records both directions. Older evidence that did not contain
an opposite-direction snapshot displays "No causal snapshot" for that side.
Compact exit-candidate rows retain the latest complete same-lane health vote
count instead of replacing it with a label-only event.

This changes observation evidence and presentation only. Existing entry/exit
rules, immutable decisions, execution, paper orders and quantity are unchanged.
