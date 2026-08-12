# RB-1.6.0 — Replay Accuracy & Decision Calibration

## Scope
Research/observability release only. No live trading thresholds, weights, Primary rules, Shadow authority, Committee policy, Portfolio limits, queue behavior, or exit rules are automatically changed.

## Added
- Replay Accuracy dashboard in Research Lab.
- Point-in-time option capture gap analysis (missing minute ranges and longest gap).
- Confidence calibration buckets.
- Advisory confidence-threshold scenarios (60/65/70/75/80).
- Minimum 30 resolved-candidate sample gate before any threshold candidate is recommended.
- Counterfactual Exit Engine outcome labels for historical WAIT/BLOCK candidates, calculated only after the original decision is frozen.
- Explicit outcome basis: EXECUTED_EXIT_ENGINE vs COUNTERFACTUAL_EXIT_ENGINE.

## Safety
Future option candles remain prohibited from entry decisions. Counterfactual outcomes are research labels only and do not affect the historical decision, live parameters, or portfolio state.
