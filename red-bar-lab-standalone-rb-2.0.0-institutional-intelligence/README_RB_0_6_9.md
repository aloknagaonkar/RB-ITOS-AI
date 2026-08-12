# RB-0.6.9 Final Stabilization Release

Final non-AI stabilization release before RB-0.7.

## Changes
- Rename ACTIVE Signals to Live / Open Signals.
- Add Completed Signals Today so completed signals remain visible.
- Add completed signal drill-down to all linked trade models.
- Add per-day occurrence numbering by level type:
  - NEXT_RED_CANDLE_1, NEXT_RED_CANDLE_2
  - FIRST_CANDLE_1
  - PD3_315_1
- Add short marker labels such as NRC-1 and FC-1.
- Preserve the original level_type and canonical signal_id for analytics.
- Add completed-signal quality summary:
  successful, failed and breakeven model counts; model success rate; best/worst
  points; best/worst exit model; MFE; MAE; completion time and lifecycle.
- Deterministic pre-AI quality labels:
  STRONG_SUCCESS, SUCCESS, MIXED, WEAK, BREAKEVEN, FAILED.

No Red Bar strategy rules, Upstox foundation, historical candles, live cache or
existing artifacts are deleted or reset.
