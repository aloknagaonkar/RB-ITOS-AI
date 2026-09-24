# Hilega Active/Exited Trade UI + Candle Timing

This cumulative patch:
- removes the old aggregate Shadow premium P&L dashboard
- removes the old mixed CE entry/exit ledger
- adds an Active CE shadow trade section that contains only ACTIVE trades
- automatically removes a trade from Active when its status changes
- adds Exited CE shadow trades at the bottom (including pending exact exits)
- preserves independent ATM±2 shadow observations; no quantity or rupee P&L
- displays candle windows like 10:35–10:40
- shows actual runtime `processed HH:MM:SS` from UNDERLYING_5M_BUILD when recorded
- shows `recovered HH:MM:SS` for bootstrap-recovered checkpoints

The backend change is reporting-only: `_related_to_checkpoint()` additionally links
`UNDERLYING_5M_BUILD.payload.bar_timestamp` to its strategy checkpoint so the UI can
display the real processing timestamp.

No strategy rules, option-entry/exit rules, execution settings, or worker behavior are changed.
