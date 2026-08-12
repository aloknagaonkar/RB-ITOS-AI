# RB-0.7.8.2 — Selected-Rank Dual-Engine Analysis

RB-0.7.8.2 changes candidate inspection so the selected Rank drives both
analysis panels.

## What changes when Rank #2-#5 is selected

The selected candidate now drives:

- Candidate Workbench
- Current Rule Engine — Selected Candidate
- New Intelligence Engine — Selected Candidate
- Rule score component display
- Greeks
- selected option candle
- Shadow Intelligence input
- agreement analysis
- Rank #1 vs selected-rank difference table

## Why Rank #N vs Rank #1?

The UI now shows a direct comparison of:

- Rule Score
- Spread
- Liquidity
- Volume
- Open Interest
- VWAP
- EMA
- Momentum
- Momentum %
- Delta
- Gamma
- IV
- Theta
- Vega

It also highlights where the selected candidate is stronger and where Rank #1
has the advantage.

## Execution safety

Automatic paper execution remains locked to Rank #1.

Selecting Rank #2-#5 changes analysis only.

The page clearly separates:

- `Automatic Paper Execution: Rank #1`
- `Currently Analysing: Rank #N`

For selected Rank #2-#5:

`Execution Impact = NONE`

## Shadow data integrity

Selected Rank #2-#5 Shadow analysis is displayed but is not inserted into the
historical execution-validation dataset.

Only Rank #1 Shadow evaluation is persisted to
`shadow_intelligence_evaluations`.

This prevents inspection activity from corrupting historical accuracy metrics.

## Performance

The Candidate Workbench, Current Rule Engine analysis, and Shadow Intelligence
analysis now live inside the same Streamlit fragment.

Changing Rank therefore updates all candidate-analysis panels together without
requiring a full Paper Trading page rerun.

## Trading logic unchanged

The automatic execution engine, score threshold, signal gates, stop, target,
EOD exit policy, and live-trading safety remain unchanged.
