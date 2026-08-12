# RB-0.7.9.2 — Exit Engine UI Completion

RB-0.7.9.2 completes the visual Paper Exit Engine discussed for CE/PE
paper positions. Exit thresholds and automatic-exit authority are unchanged.

## Three-column workstation

### Position & Protection

Displays:

- Position
- Entry
- Current premium
- Peak premium
- P&L and P&L %
- Quantity
- Holding time
- Initial SL
- Breakeven
- Trailing Stop
- Effective Stop
- Target 1
- Target 2

Protection states are displayed with explicit visual status badges:

- ACTIVE
- ARMED
- WAIT
- NEAR
- HIT
- INFO

## Exit Health

Each health condition now has both a visual state and an authority label:

Operational:

- NIFTY Thesis
- Opposite Red Bar
- Option VWAP
- Option EMA
- Momentum

Advisory:

- Volume

Shadow:

- OI / PCR
- Greeks

Operational checks are visually separated from advisory/shadow evidence so it
is clear which conditions can actually contribute to an automatic paper exit.

## Exit Decision

The operator-facing actions are now:

- HOLD
- PROTECT PROFIT
- HOLD / TRAIL
- TIGHTEN STOP
- EXIT NOW

The panel displays:

- Trade Health / 100
- Exit Pressure / 100
- Primary Reason
- Additional Confirmation
- Exit Reason Code
- Decision Reasons
- Next Trigger

The actual exit authority remains the existing `hard_exit_reason`.

## Combined exit evidence

When a hard exit occurs, the timeline now records the primary reason plus
supporting evidence such as:

- NIFTY_INVALIDATION
- OPPOSITE_RED_BAR
- VWAP_LOST
- EMA_BEARISH
- MOMENTUM_NEGATIVE
- VOLUME_WEAK

Supporting confirmations do not independently change the hard-exit hierarchy.

## Protection milestones

The automation audit trail now records transition events only when protection
actually changes:

- BREAKEVEN_ARMED
- TRAILING_ACTIVATED
- TRAIL_UPDATED

Examples:

`+15% peak reached; entry=100; peak=115; effective_stop=100`

`+20% peak reached; peak=125; trail=112.50`

`trail 112.50 -> 116.00; peak=128.89`

## Exit Timeline

The UI translates low-level execution events into a readable trade replay:

- ENTRY
- +15% · BREAKEVEN ARMED
- +20% · TRAILING ACTIVE
- TRAIL UPDATED
- MONITOR
- EXIT TRIGGERED
- EXIT / CLOSED

The timeline is collapsed by default to preserve page performance.

## Exit rules unchanged

This release does not change:

- Initial premium stop
- Target 1
- 15:25 EOD exit
- +15% breakeven trigger
- +20% trailing trigger
- 10% trail below highest premium
- NIFTY thesis invalidation
- Opposite Red Bar exit
- Two-of-three option technical breakdown
- OI/PCR/Greeks remaining Shadow-only

Live broker execution remains disabled.
