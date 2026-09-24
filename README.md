# Hilega Bearish Phase B3 — Historical Replay

Adds a separate bearish historical replay path while preserving the current bullish engine/replay.

Outputs per target session:
- `step-audit.jsonl`
- `bearish-trades.csv`
- `bearish-signal-decision-audit.csv/json`
- `bearish-candle-by-candle-audit.csv/json`
- `bearish-manual-validation.txt`

Multi-session outputs:
- `multi-session-bearish-summary.json`
- `multi-session-bearish-sessions.csv`
- `multi-session-bearish-trades.csv`
- `multi-session-bearish-signal-decision-audit.csv`
- `multi-session-bearish-candle-by-candle-audit.csv`

The replay is observation/research only and explicitly marks the rules as:
`CANDIDATE_MIRROR_UNDER_VALIDATION`.

Validated against the uploaded code snapshot:
`25 passed` across existing bullish strategy tests + bearish strategy + bearish historical replay tests.
