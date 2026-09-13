# Midpoint Four-Arm Decision Research V1

This phase converts the symmetric structural framework into standardized
research decisions.

## Four independent arms

| Arm | Structural path | TRADE_NOW option |
|---|---|---|
| RED bearish continuation | RED midpoint down -> low break -> continuation | PE |
| RED bullish reclaim | RED downside break fails -> midpoint reclaims up | CE |
| GREEN bullish continuation | GREEN midpoint up -> high break -> continuation | CE |
| GREEN bearish reclaim | GREEN upside break fails -> midpoint reclaims down | PE |

Each arm derives its own thresholds from TRAIN only.

OOS-A/B/C/D are validation only.

## Decision checkpoint

T+3 minutes after:

- boundary break for continuation arms;
- midpoint reclaim for reclaim arms.

Output is one of:

- `TRADE_NOW`
- `WAIT`
- `CANCEL`

`CANCEL` is allowed only when the opposite reclaim/failure has already happened
by the T+3 decision timestamp.

## Frozen feature family

Nine features are used in every arm:

1. directional 5m momentum
2. directional distance beyond boundary
3. directional acceptance %
4. consecutive closes beyond boundary
5. new directional close-extreme count
6. directional progress
7. directional velocity
8. favored-option 5m premium change
9. opposite-option 5m OI change

"Directional" means positive values consistently represent progress in the
active setup direction. This makes bearish and bullish rules structurally
symmetric.

Option mapping:

- bearish arm: favored option = PE; opposite option = CE
- bullish arm: favored option = CE; opposite option = PE

PCR remains diagnostic/contextual and is not in the nine-feature score.

## Standard event output

Every decision record contains:

- session_date
- block
- setup_type
- reference_candle
- break_direction
- break_time
- decision_time
- decision
- option_side
- score
- score_max
- evidence_score_pct
- reason_codes
- actual_outcome
- feature_values / feature_passes

## Small reclaim samples

The reclaim arms have smaller TRAIN samples than primary continuation arms.
The module explicitly emits a `low_sample_warning` whenever either TRAIN class
contains fewer than five observations.

A low-sample arm must remain exploratory even if pooled accuracy looks good.

## No P&L yet

This phase does not select strikes, entries, stops, targets, quantity, or
calculate realized option returns.

Only after block-level OOS validation should a surviving arm move to exact
ATM option-path backtesting.
