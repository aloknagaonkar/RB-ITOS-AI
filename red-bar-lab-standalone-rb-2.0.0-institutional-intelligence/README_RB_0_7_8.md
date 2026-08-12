# RB-0.7.8 — Candidate Workbench

RB-0.7.8 separates execution, candidate inspection and Shadow Intelligence.

## Core rule

Rank #1 remains the ONLY automatic paper execution candidate.

Selecting Rank #2–#5 changes inspection only. It cannot affect:

- Current Decision Engine
- candidate ranking
- BUY / WAIT
- paper entry
- paper exits
- Shadow Intelligence
- live execution

## Top-5 table

The Top Ranked Candidates table remains a static comparison view containing all
five ranked CE/PE candidates.

## Radio candidate selector

Immediately below the Top-5 table, the UI now shows:

- Rank #1
- Rank #2
- Rank #3
- Rank #4
- Rank #5

as a horizontal radio control.

The selected rank is resolved to its exact option symbol and stored as the
inspection candidate.

## Candidate Workbench

The Candidate Workbench now appears immediately under the Top-5 selection area,
before the Current Decision Engine / Shadow Intelligence comparison.

It displays the selected candidate's:

- Rank
- Contract
- Rule Score
- Candidate Health
- Health Band
- Entry Reference
- Stop
- Target 1
- Target 2
- Decision
- Spread
- Liquidity
- Volume
- Open Interest
- VWAP
- EMA9 / EMA21
- Momentum
- Delta
- Gamma
- IV
- Theta
- Vega
- Strengths
- Weaknesses
- Why Rank #1 / Why Not Rank #1
- selected option candle with Close / EMA9 / EMA21 / VWAP

A visible banner identifies the exact option being inspected.

## Execution vs Inspection

A dedicated summary makes the separation explicit:

### Execution Candidate

Always Rank #1 and retains execution authority.

### Inspection Candidate

The radio-selected Rank #1–#5 candidate.

For Rank #2–#5:

`Execution Impact = NONE`

## Current Decision Engine

The Current Decision Engine remains driven by:

`ranked_rows[0]`

It does not change when another candidate is inspected.

## Shadow Intelligence

Shadow Intelligence remains unchanged and observation-only.

## Compare Two Candidates

A new read-only comparison panel lets the user select Candidate A and
Candidate B from the Top-5.

It compares:

- Rule Score
- Spread
- Liquidity
- Volume
- Open Interest
- VWAP
- EMA
- Momentum
- Delta
- Gamma
- IV
- Theta
- Vega

The panel identifies the ranking winner based on the existing rule score.

This comparison has no execution impact.

## Safety

The automatic paper execution engine is unchanged.

Live broker execution remains hard-disabled.
