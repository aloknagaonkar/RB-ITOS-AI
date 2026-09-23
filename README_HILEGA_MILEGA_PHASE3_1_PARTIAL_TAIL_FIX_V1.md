# Hilega-Milega Phase 3.1 — Live Partial 5m Tail Fix

## Defect found in first real live run

At 09:37 the Upstox 1-minute intraday response already contained 09:35 and
09:36 while the 09:35 five-minute slot was still forming.  The live bootstrap
passed all intraday rows into the strict historical `aggregate_exact_5m()`
function, which correctly rejected the partial slot as missing 09:37-09:39.

This is a live orchestration bug, not a strategy-rule bug.

## Fix

Before strict 5-minute aggregation, live code now trims the intraday source to
only the minute rows belonging to five-minute bars whose label is at or before
`latest_completed_5m_label(now)`.  The currently forming slot is never passed
into the indicator/strategy engine.

The same causal trimming is applied in both bootstrap/restart reconstruction and
normal live processing.  The 14:55 open cutoff remains separate and unchanged.

## Strategy impact

None. Entry, exit, Route A, Route B, opening-path and 14:55 rules are unchanged.

## Added regression coverage

- bootstrap at 09:37 with a partial 09:35 slot
- normal process at 10:07 with a partial 10:05 slot

Both must ignore the partial tail and process only completed 5-minute bars.
