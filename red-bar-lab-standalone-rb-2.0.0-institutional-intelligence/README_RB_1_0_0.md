# RB-1.0.0 — Expectancy Engine

RB-1.0.0 replaces the opportunity-shrunk EV model with an expectancy model while preserving the existing Institutional Execution Committee, queue, lifecycle and paper-exit architecture.

## Core formula

`Expectancy = P(win) × Expected Win − P(loss) × Expected Loss`

The configured target/stop remain the payoff prior. When comparable closed paper trades exist, historical average winner/loss are blended in gradually (up to 60% authority by 50 samples).

Opportunity Remaining no longer shrinks the target. It applies an explainable confidence multiplier to execution probability: 90–100%=1.00, 70–90%=0.95, 50–70%=0.90, 30–50%=0.80, below 30%=0.60.

The UI exposes execution probability, expectancy, expected win/loss, expectancy confidence, source and a capped half-Kelly research value. Half-Kelly is informational only; position sizing is unchanged in this release.

`expected_value_pct` remains populated as a backward-compatible alias for expectancy so previous reports and queue records continue to work.
