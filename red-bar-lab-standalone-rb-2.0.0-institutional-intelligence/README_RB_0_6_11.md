# RB-0.6.11 Quality Visibility & Backtest Filtering

Pre-AI usability improvement on top of RB-0.6.10.2.

## Quality visibility

Every signal now shows a human-readable actionable outcome:

- `10W / 0L / 0BE`
- `9W / 1L / 0BE`
- `3W / 6L / 1BE`

It also shows an actionable score:

- `10/10`
- `9/10`
- `3/10`

## Quality bands

Based on number of successful actionable models:

- GREEN / 🟢 : 9–10 wins
- YELLOW / 🟡 : 6–8 wins
- ORANGE / 🟠 : 3–5 wins
- RED / 🔴 : 0–2 wins

These are visual classifications only and are not AI confidence.

## Backtest filters

Existing filters:
- Signal Type
- Direction
- Exit Model
- Trade Result

New filters:
- Signal Quality
- Minimum Success Score: 3+/10, 6+/10, 8+/10, 9+/10, 10/10

## Rules unchanged

- 10 actionable models determine signal completion and quality.
- EOD_HOLD remains informational benchmark only.
- No entry, confirmation, stop, target, or Upstox rules change.
