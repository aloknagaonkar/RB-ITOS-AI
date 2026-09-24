# Preserve Existing Hilega UI + Add Bearish Semantics

Corrective frontend-only patch.

- Restores the original `HilegaDecisionTable` in Historical Replay and Live Shadow.
- Keeps the same filters, columns, cards, row expansion, audit detail, and CSS.
- Uses the existing directional-candle API only as a data overlay.
- Adds bearish decision labels/semantics inside the existing UI.
- No strategy, coordinator, CE/PE lifecycle, selector, quantity, or execution changes.
