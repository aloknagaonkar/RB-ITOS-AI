# Opening Red Candle Midpoint Evidence Research V1.1

This is a narrow research patch over V1. It does **not** add a trading rule.

## What V1.1 fixes

### 1. Early-session price feature availability

V1 discarded all price features when less than 15 minutes of history existed.
V1.1 keeps every feature whose own lookback is available:

- 1m momentum after 1 prior minute
- 5m momentum after 5 prior minutes
- EMA(5) after 5 closes
- EMA(15) after 15 closes
- 15m momentum and 15m realized volatility only when 15m history exists

Missing longer-lookback fields remain `null`; shorter valid fields are retained.

## What V1.1 adds

At low-break T0 and T+1/T+3/T+5 the evidence snapshot now also measures:

- minutes since low break
- percentage of closes below original midpoint
- percentage of closes below reference low
- consecutive closes below midpoint
- consecutive closes below reference low
- reference-low recross count
- new closing-low count
- net downside progress
- downside velocity
- close-range and full-range after break
- maximum rebound from the post-break low close
- existing midpoint-cross count

These are current/backward-only features. They are allowed to become later
`TRADE / WAIT / CANCEL` inputs because they do not use future data.

## Future-only path diagnostics

The outcome section now records:

- `outcome_path_shape`
- pre-resolution acceptance below midpoint
- pre-resolution acceptance below reference low
- midpoint/refererence-low crossing counts
- new-low count
- close/full range
- net downside progress
- full 30-minute path metrics

These remain **labels/diagnostics**, not entry features.

V1.1 intentionally keeps the existing outcome labels so V1 and V1.1 are
comparable:

- `BREAK_AND_GO`
- `BREAK_AND_BASE_THEN_GO`
- `FALSE_BREAK_RECLAIM`
- `SIDEWAYS_NO_CONTINUATION`
- `NO_LOW_BREAK`
- `NO_MIDPOINT_BREAK`

`BREAK_AND_BASE_THEN_GO` still means delayed continuation (>5m and <=30m).
The new path metrics let us determine whether those delayed cases truly based,
ground down slowly, or chopped before continuation rather than assuming that
delay automatically equals a base.

## Research discipline

Only TRAIN + OOS-A/B/C/D.

No E/F/G/H.

OI, volume and PCR are still descriptive confirmation evidence only.
No thresholds are promoted to a trading rule in this patch.
