Phase 6.2.2 corrective frontend-only patch.

Keeps the restored original HilegaDecisionTable UI.

Fixes missing live signals by:
1. matching directional rows to audit checkpoints by absolute epoch-minute, and
2. supplementing missing directional ENTRY/EXIT rows from the already-recorded
   directional trade dashboard.

No strategy signal is recalculated and no market data is synthesized.
