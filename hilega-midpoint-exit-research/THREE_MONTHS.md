# Three-month run and daily reports

Suggested current window: August, September and October through captured22Oct.
Use repeated --month2026-08 --month2026-09 --month2026-10 (with spaces).
Use July instead of October if the intended window is July–September; no code
change is needed. Saved input coverage is not exchange-calendar certification.

Rules unchanged from BODY50_1M_WAIT. New output captures all tested5m policy
events, entries, exits and opposite-monitor state, plus1m waiting checks. Full
baseline replay audit is included separately in each daily report. No new live
instrumentation or strategy changes. This does not reconstruct unavailable
canonical engine internals or arms that were not emitted in the recorded result.

Outputs:
- summary.md: total/monthly/daily results and impact.
- signal-comparison.md: union of executed setup identities, both strategies.
- signal-values.md: detailed indicators/body/breakout values for tested trades.
- daily-trades.md: all trades under both policies.
- daily-report-index.md: links to daily-reports/YYYY-MM-DD.md.
- daily-reports: executions, all tested evaluations, baseline audit evidence.
- YYYY-MM-DD.json: full machine-readable session results.

Use new output directory. Resume with identical command and source/input files.
One process per directory. No tests/replays run locally; validate on Ubuntu VM.
