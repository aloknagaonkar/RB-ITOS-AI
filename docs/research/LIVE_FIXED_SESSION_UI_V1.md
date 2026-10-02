# LIVE_FIXED_SESSION_UI_V1

Read-only bridge from the live fixed-anchor journal into the existing PCR workspace.

## Source precedence
- `ANCHOR_LIVE`: genuine live fixed anchor captured in the normal window.
- `ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M`: exact recovered anchor when the live anchor was missed.
- No journal anchor: legacy stored PCR evaluation remains unchanged.

The projection never rewrites stored Observation/Evaluation rows or PCR history.

## Display semantics
The Fixed morning ATM summary card and Observation inspector use the same exact fixed basket.
Per-strike CE/PE deltas are from the fixed-session anchor baseline to the selected observation,
not provider `prev_oi`.

Recovered sessions are visibly labelled `RECOVERED ANCHOR`; genuine captures are `LIVE ANCHOR`.

## Strictness
No nearest strike, timestamp, key, interpolation, synthetic OI, or partial-basket substitution.
Any missing exact current anchored instrument makes the fixed-session projection INCOMPLETE.

## Trends
5m, 15m and 30m Fixed-PCR changes use prior projected observations from the same session,
with the existing configured timestamp tolerance.

No strategy, ALL3, paper-order, or live-execution behavior is changed.
