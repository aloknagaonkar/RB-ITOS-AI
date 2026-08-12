# RB-0.7.9 — CE/PE Paper Exit Engine v1

RB-0.7.9 introduces active paper-position management for long CE/PE trades.

## Removed UI panel

The following candidate panel was removed as requested:

- Execution Candidate
- Inspection Candidate
- Execution vs Inspection
- Compare Two Candidates

Candidate analysis itself remains available through the Rank #1–#5 selector,
Candidate Workbench, and selected-rank dual-engine analysis.

## Paper Exit Engine

A new `Paper Exit Engine` section appears under the selected Open Paper
Position.

It uses three columns:

### Position & Protection

Shows:

- contract
- entry
- current premium
- peak premium
- P&L / P&L %
- quantity
- holding time
- initial stop
- breakeven state
- trailing stop
- effective stop
- Target 1
- Target 2

### Exit Health

Shows:

- NIFTY thesis
- opposite Red Bar
- option VWAP
- option EMA9 / EMA21
- option momentum
- option volume
- OI / PCR shadow evidence
- Greeks shadow evidence
- technical-failure count

### Exit Decision

Shows:

- HOLD / HOLD-PROTECT / HOLD-TRAIL / TIGHTEN / EXIT
- Trade Health 0–100
- primary exit trigger
- next trigger
- decision reasons

## Operational exit hierarchy

Automatic paper exit authority follows this hierarchy:

1. effective premium stop
2. Target 1
3. 15:25 EOD
4. NIFTY thesis invalidation
5. confirmed opposite Red Bar after entry
6. option technical breakdown

OI/PCR/Greeks are displayed as Shadow Exit evidence and do not trigger an
automatic exit in this release.

## Breakeven protection

When peak option premium reaches +15% from entry:

- breakeven becomes armed
- effective stop may move to entry
- the stop is never loosened

## Trailing protection

When peak option premium reaches +20%:

- trailing protection activates
- trailing stop = 10% below the highest premium seen
- effective stop uses the strongest available protection

Example:

Entry 100
Peak 125
Trailing stop = 112.50

## NIFTY thesis invalidation

The original confirmed Red Bar candle provides the thesis boundary.

For BEARISH / BUY PE:

- NIFTY above confirmation high -> thesis invalid

For BULLISH / BUY CE:

- NIFTY below confirmation low -> thesis invalid

This is evaluated from the current shared Upstox underlying snapshot.

## Opposite Red Bar

A new confirmed opposite Red Bar after the paper entry is an operational exit
condition.

The exit engine closes the current virtual CE/PE position before any future
reverse logic is considered.

## Option technical breakdown

The option premium itself is evaluated using:

- close vs VWAP
- EMA9 vs EMA21
- short-term momentum

At least two failures produce:

`OPTION_TECHNICAL_BREAKDOWN`

## Exit reason codes

The engine can now close with:

- AUTO_STOP_LOSS / AUTO_HARD_STOP
- AUTO_TARGET
- AUTO_EOD_EXIT
- AUTO_BREAKEVEN_STOP
- AUTO_TRAILING_STOP
- AUTO_NIFTY_INVALIDATION
- AUTO_OPPOSITE_RED_BAR
- AUTO_OPTION_TECHNICAL_BREAKDOWN
- MANUAL_COMMAND_CENTER_EXIT

The historical legacy `AUTO_TARGET` reason is preserved for compatibility.

## Persistence

Open paper orders now persist:

- initial_stop_price
- breakeven_armed
- trailing_active
- trailing_stop_price
- exit_health_score
- exit_action
- exit_detail

The migration is additive and existing databases are backfilled with the
existing stop as the initial stop.

## Exit Timeline

The Exit Engine includes a collapsed `Exit Timeline` showing:

- EXIT_MONITOR
- EXIT_TRIGGERED
- CLOSED

events for the selected trade.

## Safety

This release affects PAPER execution only.

Live broker order placement remains hard-disabled.
