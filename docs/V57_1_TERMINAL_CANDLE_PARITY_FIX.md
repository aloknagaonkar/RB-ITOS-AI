# V57.1 — terminal-candle structural observation parity fix

Diagnosis confirmed that all five B3 timestamp mismatches occurred exactly on
the currently active lifecycle's `STRUCTURAL_TERMINAL` candle.

Previous behavior returned from `_process_minute` immediately after the
terminal, so the opposite structure was not observed on that candle.

V57.1:
- continues structural observation after a terminal
- records opposite `BOUNDARY_BREAK` and `BOUNDARY_CLASSIFIED` on the true candle
- allows B to arm its delayed watch on that candle
- explicitly blocks immediate E entry on that same candle with
  `E_ENTRY_BLOCKED / SAME_CANDLE_REVERSAL_BLOCKED`
- preserves no-same-candle reversal
- changes no B/E threshold or Candidate-A rule
