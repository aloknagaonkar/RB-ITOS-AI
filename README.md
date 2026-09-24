Live signal marker overlay v4

Frontend-only corrective patch.

It preserves the existing HilegaDecisionTable UI and injects already-recorded
directional trade ENTRY/EXIT events directly into the canonical audit rows.

Matching:
- entry: signal_bar, fallback signal_boundary - 5 minutes
- structural exit: exact option exit boundary - 5 minutes
- cutoff exit: exact 14:55 boundary

No strategy signal is recalculated.
