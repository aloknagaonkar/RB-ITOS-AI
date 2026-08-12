# Red Bar Lab Roadmap

## RB-0.6.12 — Trader Experience — CURRENT
- One Live page; no additional tabs
- Precise Entry Time / Price / Stop
- Current P/L and EOD benchmark side by side
- Trader-friendly trade status
- Exact actionable completion time
- Best exit model / time / price / points
- EOD exit time / price / points
- Targets and marker/quality visibility retained
- Same-page Trade Timeline

## RB-0.6.11 — Quality Visibility & Filtering
- Human-readable quality explanation (10W / 0L / 0BE)
- Actionable score (10/10)
- GREEN/YELLOW/ORANGE/RED visual bands
- Signal Quality backtest filter
- Minimum Success Score backtest filter
- Cleaner live and completed signal interpretation

## RB-0.6.10 — Pre-AI Evaluation Freeze
- 10 actionable exit models
- 1 informational EOD benchmark
- Signal completes when actionable_closed == 10
- EOD benchmark does not keep signal open
- Separate lifecycle and signal outcome
- Live actionable success/failure/breakeven counters
- Separate benchmark RUNNING/CLOSED and current/final points
- Completed Signals Today
- Signal occurrence numbering
- Target progress
- Signal drill-down
- Backtest filters:
  - Signal Type
  - Direction
  - Exit Model
  - Trade Result
- Filtered backtest summary

## RB-0.7 — Intelligence
- Explainable confidence
- Historical setup ranking
- Best exit recommendation
- Expected move
- Level/direction/confirmation-delay intelligence
- Time-of-day/weekday intelligence
- Historical matching

## RB-0.8 — Options Intelligence
- CE/PE ranking
- OI / change in OI
- PCR
- IV / Greeks
- Volume / liquidity
- Historical option-premium outcomes

## RB-0.9 — Learning & Stability
- Rolling-window performance
- Out-of-sample validation
- Pattern ranking
- Confidence calibration
- Regime stability

## RB-1.0 — Validation Gate
- Historical validation
- Live paper validation
- Promotion decision before ITOS integration
