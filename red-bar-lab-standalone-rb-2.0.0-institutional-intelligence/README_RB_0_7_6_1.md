# RB-0.7.6.1 — Portfolio Intelligence + Shadow Intelligence

RB-0.7.6.1 introduces a new observation-only intelligence layer while keeping
the existing paper execution decision engine frozen.

## Core safety rule

The existing automatic paper execution engine remains the only component with
execution authority.

The new Shadow Intelligence Engine has:

`Execution Impact = NONE`

It cannot:

- open a paper trade
- block a paper trade
- close a paper trade
- reverse a paper trade
- hedge a paper trade
- modify a stop or target

This release is designed for evidence collection and side-by-side evaluation.

## Current Decision Engine — unchanged

The existing paper path remains:

1. confirmed Red Bar signal
2. market-hours gate
3. signal freshness
4. duplicate protection
5. BULLISH -> CE / BEARISH -> PE
6. option candidate discovery
7. existing candidate score
   - spread
   - liquidity
   - volume
   - OI
   - VWAP
   - EMA9/EMA21
   - momentum
8. minimum candidate-score threshold
9. valid option ask/LTP
10. virtual paper execution

No Shadow Intelligence module is imported into or called by
`execution/automation.py`.

## New Shadow Intelligence

The Paper Trading page now displays two engines side by side:

### LEFT

`CURRENT DECISION ENGINE — EXECUTION ACTIVE`

Color-coded rows show the current hard gates and weighted candidate-score
inputs.

### RIGHT

`NEW INTELLIGENCE ENGINE — SHADOW MODE · OBSERVE ONLY`

Each module shows four independent attributes:

- Status
- Direction
- Confidence
- Recommendation

and also displays the reason.

Example:

`PCR -> PASS / BULLISH / 82% / BUY CE`

The fields are independently color-coded.

## Shadow modules in RB-0.7.6.1

### PCR Intelligence

Observation bands:

- PCR >= 1.10 -> bullish observation
- PCR <= 0.90 -> bearish observation
- otherwise -> neutral observation

These thresholds are experimental shadow thresholds, not trade gates.

### OI Change Intelligence

Compares aggregate live call and put change-in-OI from the current option chain.

Outputs:

- BUY CE
- BUY PE
- WAIT

Observation only.

### Max Pain

Shown as informational / neutral.

Max Pain is deliberately not treated as a directional trade trigger.

### Call / Put Wall

Compares spot with current call and put OI walls.

Outputs a directional or range observation.

### Greeks

Evaluates the currently best ranked option's:

- Delta
- Gamma
- IV
- Theta
- Vega

This is a contract-quality observation only.

### Market Context

Uses persisted entry-time `trend_5m` when available.

If no decisive context exists, it reports NEUTRAL instead of inventing a
direction.

### Market Structure

Uses the existing persisted:

- bullish structure score
- bearish structure score
- structure state

### Volume Intelligence

Uses persisted:

- relative volume
- short-term volume trend

### Multi-Timeframe

Explicitly displays `DATA PENDING` until a validated 15m/5m/1m alignment
feature is persisted.

### Wyckoff

Explicitly displays `DATA PENDING` until a validated Wyckoff entry-time phase
feature is persisted.

The system does not fabricate these observations.

## Portfolio Intelligence

The shadow engine now detects current paper exposure.

Examples:

- no open position -> `ALLOW`
- current signal CE while PE is open -> `CONFLICT / REVERSE`
- current signal PE while CE is open -> `CONFLICT / REVERSE`
- same-direction exposure already open -> `HOLD`

All of these are OBSERVATION ONLY.

Automatic reversal is NOT enabled.

## Shadow Committee

Directional shadow modules vote on:

- BUY CE
- BUY PE
- WAIT

The page shows:

- Shadow Decision
- Shadow Confidence
- Agreement with the current engine
- Portfolio Action
- Portfolio Conflict

Portfolio `REVERSE` remains a separate suggested portfolio action and is not
silently converted into an execution.

## Color language

The UI now uses a consistent color vocabulary:

- green -> PASS / strong / BUY
- yellow -> neutral / WAIT / mixed
- orange -> warning / weak
- red -> FAIL / reject
- purple -> portfolio conflict / reverse / hedge
- blue -> information
- grey -> shadow / observation-only

## Persistence

New table:

`shadow_intelligence_evaluations`

It stores:

- Signal ID
- trading date
- current-engine decision
- shadow decision
- shadow confidence
- agreement
- portfolio conflict
- portfolio action
- module details
- evaluation time
- execution impact = NONE

This is the foundation for later historical comparison.

## Operations Center

Operations Center now also shows:

- Open CE count
- Open PE count
- Net portfolio exposure
- Latest shadow decision
- Portfolio conflict
- Suggested shadow portfolio action
- Latest agreement and confidence

It is clearly marked:

`SHADOW MODE · EXECUTION IMPACT = NONE`

## Stable navigation

The RB-0.7.5 URL-based workspace persistence remains in place, so automatic
browser refresh should stay on the selected workspace.

## Validation

The release includes regression tests proving:

- Shadow Engine can produce directional observations
- Portfolio conflict can suggest REVERSE
- every shadow module has execution impact NONE
- Shadow evaluations persist correctly
- current execution automation does not import Shadow Intelligence
- side-by-side UI exists
- all previous Red Bar tests continue to pass

## Next planned release

`RB-0.7.6.2 — Shadow Validation & Operations Center 2.0`

Planned:

- historical shadow accuracy
- agreement-vs-outcome analytics
- detailed missing-options diagnosis
- recent event stream
- richer signal/recommendation statistics
- reverse "would-have" outcome tracking

No new intelligence will be promoted into the Current Decision Engine without
explicit validation and approval.
