# Midpoint V3.2 False-Positive Diagnostics V1

The exact-option economics showed that the aggregate 77-confirmation result is
being heavily influenced by a very small number of structural false positives.

This module isolates those events without changing V3.2.

## Groups

```text
TRUE CONFIRMATION
V3.2 state = CONFIRM_CONTINUATION
future structural outcome = CONTINUATION

FALSE POSITIVE
V3.2 state = CONFIRM_CONTINUATION
future structural outcome = REVERSAL
```

Future outcome is allowed only for retrospective diagnostics. It is explicitly
forbidden as a live entry feature.

## Compare

At T+3:

- acceptance_pct
- momentum_5m_directional
- progress_points
- giveback_from_best_checkpoint_points
- consecutive_closes
- velocity

Also:

- direction
- block
- T+1 observation state
- T+3 OI quality
- exact T+1 -> T+3 OI transition
- exact option economic damage

## Important restriction

This module does NOT:
- select a new threshold;
- create a new entry filter;
- optimize P&L;
- touch OOS-E/F/G/H;
- emit orders.

Its purpose is to explain the false confirmations before deciding whether a new
TRAIN-only structural hypothesis is justified.
