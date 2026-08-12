# RB-0.6.12.1 Current Trade Dashboard UI Patch

UI-only patch.

Adds a compact `Current Trade Dashboard` immediately above `Live / Open Signals`.

Columns:
- Priority
- Signal
- Status
- Entry Time (IST)
- Entry Price
- Current Price
- Current P/L
- Exit Time (IST)
- Exit Price
- Best P/L
- Score
- Quality

Exit Time and Exit Price remain empty until all 10 actionable models are closed.
Once actionable completion occurs, they are taken from the final actionable
model to close and remain frozen.

No strategy, database, signal, exit-model, benchmark, Upstox, or backtest logic
is changed.
