# Opening Candle Midpoint Reversal Framework V1.1

This is a methodology-only patch to V1.

## Fix

V1 recorded a reclaim timestamp even when the primary continuation target had
already been reached first. `build_event()` then launched reclaim research for
that later reclaim as well.

That contaminated reclaim statistics because an event could count as:

- successful primary continuation, and later
- a reclaim reversal setup.

V1.1 keeps the later reclaim timestamp for diagnostics but allows reclaim-path
research only when reclaim **wins the primary path race**:

- `RED_BREAK_BULLISH_RECLAIM`
- `GREEN_BREAK_BEARISH_RECLAIM`

Therefore:

- RED bullish reclaim event count must equal RED primary bullish-reclaim count.
- GREEN bearish reclaim event count must equal GREEN primary bearish-reclaim count.

No thresholds, labels, continuation levels, or source data are otherwise
changed.

TRAIN + OOS-A/B/C/D only. E/F/G/H remain untouched.
