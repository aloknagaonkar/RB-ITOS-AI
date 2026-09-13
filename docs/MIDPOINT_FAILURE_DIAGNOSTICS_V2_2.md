# Midpoint Failure Diagnostics V2.2

V2.2 corrects the diagnostic layer before any CONFIRM/WAIT/CANCEL state machine
is frozen.

## Correction 1 — bearish momentum orientation

The opening midpoint framework already guarantees that directional features have
the same positive=favorable semantics on RED/bearish and GREEN/bullish paths.

V2 accidentally negated bearish momentum again. V2.2 restores:

```text
positive directional momentum = favorable continuation
negative directional momentum = deterioration / opposite pressure
```

for both directions.

## Correction 2 — exact T+1 -> T+3 OI transitions

The previous diagnostic sliced to one checkpoint before attempting to pair
T+1 and T+3, so transition dictionaries were empty.

V2.2 groups the complete event first and emits exact transitions such as:

```text
CE:SHORT_BUILDUP->SHORT_COVERING;
PE:LONG_BUILDUP->LONG_UNWINDING
```

All four states remain valid:
LONG_BUILDUP, SHORT_BUILDUP, LONG_UNWINDING, SHORT_COVERING.

## Correction 3 — giveback / decay from available checkpoints

The source V2 rows do not contain raw rebound_points or midpoint_cross_count.
V2.2 does not fabricate them.

Instead it derives from T0/T+1/T+3 directional progress:

- giveback_from_best_checkpoint_points
- progress_change_from_previous_checkpoint
- acceptance_change_from_previous_checkpoint

This directly measures whether a boundary breakout is extending or giving back
its progress at the checkpoints we actually possess.

## Leakage guard

TRAIN + OOS-A/B/C/D only.
E/F/G/H excluded.
No P&L.
No new thresholds.
No entry rule changes.
No trade orders.
