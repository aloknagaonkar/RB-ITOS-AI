# RB-0.9.0 — Opportunity Extension Entry Engine

RB-0.9.0 changes how PAPER entry handles confirmed Red Bar signals older than
the normal 180-second freshness window.

## Fresh signals

Signals at or below 180 seconds continue through the existing Current Decision
Engine. Existing candidate score, duplicate, market-hours and entry controls
remain in force.

## Old signals

A signal older than 180 seconds is no longer rejected solely because of age.

It enters the Opportunity Extension Engine.

Automatic PAPER entry is permitted only when all guarded extension conditions
pass:

- Opportunity Health >= 85
- candidate score >= 85
- reward remaining >= 40%
- original Red Bar structure remains valid
- no confirmed opposite Red Bar
- spread score >= 8
- liquidity score >= 15
- VWAP supportive
- EMA supportive
- momentum score >= 6
- normal market-hours gate still passes
- duplicate execution protection still passes
- valid candidate/quote and normal paper capital controls still pass

Signal age remains part of Opportunity Health as a soft penalty rather than an
automatic rejection.

## Opportunity Health

The first deterministic score is 0-100:

- Red Bar structure: 25
- momentum continuation: 20
- reward remaining: 20
- option technical/execution health: 15
- volume/OI market context: 10
- time decay: 10

The weights are deliberately transparent so historical results can later be
used to refine them.

## Reward Remaining

The first model measures how much of a continuation move remains using the
original confirmation-candle range. Two confirmation-candle ranges beyond the
confirmation close is treated as fully consumed.

This is an empirical proxy, not a claim about future return. All evaluations
are stored so the model can later be replaced with a data-fitted expected-move
model.

## Recording

Every opportunity evaluation is written to `opportunity_evaluations`,
including fresh and extended signals.

Opportunity-extension trades are also tagged on the paper order with:

- entry_mode = OPPORTUNITY_EXTENSION
- signal_age_at_entry
- opportunity_score
- reward_remaining_pct

Fresh entries are tagged `FRESH_SIGNAL`.

Execution-state events include:

- OPPORTUNITY_EVALUATED
- OPPORTUNITY_EXTENSION_APPROVED
- SKIPPED_OPPORTUNITY

This allows later comparison of Fresh Signal entries versus Opportunity
Extension entries.

## UI

Paper Trading now shows `Opportunity Intelligence Engine` below Current Red Bar
Decision / Automatic Execution Eligibility.

The panel displays:

- Entry Mode
- Signal Age
- Opportunity Health
- Reward Remaining
- Move Consumed
- Decision
- Structure
- Momentum
- Option Health
- Market Context
- Time Decay
- Opposite Red Bar
- approval/rejection reason

## Safety

This change affects PAPER execution only.

Market-hours, duplicate protection, candidate validation, paper capital limits,
and the RB-0.7.9 Exit Engine remain active.

Live broker execution remains hard-disabled.
