# RB-0.6.10 Pre-AI Evaluation Freeze

This is the final structural release before RB-0.7 Intelligence.

## 10 Actionable Models
The following 10 models determine signal completion and signal quality:

1. Fixed Target 20
2. Fixed Target 30
3. Fixed Target 40
4. Fixed Target 50
5. Risk/Reward 1R
6. Risk/Reward 2R
7. Risk/Reward 3R
8. Trailing Stop 10
9. Trailing Stop 20
10. Break-even @ 1R

A signal becomes `COMPLETED` when all 10 actionable models are closed.

## Model 11 — Informational Benchmark
`EOD_HOLD` is informational only.

It does NOT:
- keep the signal open;
- count toward actionable success/failure;
- affect actionable success rate;
- affect signal quality.

It continues to report:
- RUNNING / CLOSED
- current/final EOD points
- MFE
- MAE

## Separate Lifecycle and Outcome
Lifecycle:
WAITING → ACTIVE → TRADE_OPEN → COMPLETED

Outcome:
STRONG_SUCCESS / SUCCESS / MIXED / WEAK / BREAKEVEN / FAILED

## Backtest Filters
Bulk Backtest adds filters for:
- Signal Type
- Direction
- Exit Model
- Trade Result

Filtered summaries recalculate actionable rows, win rate, average points,
best/worst points, and benchmark-row count.

## Frozen Strategy Rules
No changes to:
- reference midpoint definitions;
- 5-minute crossing logic;
- 1-minute confirmation logic;
- stop rules;
- Upstox foundation.

After live and historical validation of this release, RB-0.7 Intelligence
should learn only from this frozen data definition.
