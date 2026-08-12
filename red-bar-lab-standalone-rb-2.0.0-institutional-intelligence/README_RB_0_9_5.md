# RB-0.9.5 — Transparent Performance Gate + Soft Scoring

RB-0.9.5 removes the hidden hard veto created by the legacy Performance Selection score while preserving execution safety.

## TSS — Trade Selection Score
TSS is a 0–100 evidence score composed of:
- Candidate/rule quality: 35%
- Opportunity health: 20%
- Historical performance: 25%
- Reward/risk: 10%
- Execution quality (spread + liquidity): 10%

TSS remains visible and contributes to the Institutional Execution Committee probability model. A TSS below the historical 70 reference is now recorded as SOFT_EVIDENCE and does not independently veto a trade.

## Hard vs soft controls
Performance Selection hard-blocks only invalid spread/liquidity execution quality. Duplicate protection, market-hours checks, capital and contract validity continue to be enforced by the surrounding paper-execution architecture. Candidate score, Opportunity Extension quality, TSS and mature historical metrics are soft evidence.

The Committee still requires its estimated probability threshold (default 70%) and positive expected value. Expected reward is now scaled by Opportunity Remaining before EV is calculated, preventing a fully-consumed stale move from receiving an unrealistic full-target EV.

## Explainability
Performance and Committee reasons now include the exact hard blocker or soft evidence values. Generic PERFORMANCE_SELECTION-only explanations are removed from the final committee decision path.

## Validation
206 tests pass.
