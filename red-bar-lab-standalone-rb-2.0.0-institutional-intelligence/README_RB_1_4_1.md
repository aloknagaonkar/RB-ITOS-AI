# RB-1.4.1 — Primary-Only Execution Authority

This stabilization release makes exactly one execution-authority change:

- Primary Decision Engine remains authoritative.
- Shadow Intelligence remains calculated, persisted, displayed and available to replay/analytics.
- Shadow bonus/penalty is removed from execution confidence (`shadow_adjustment_pct = 0`).
- Execution probability/final confidence equals Primary confidence.
- Existing Committee threshold, expectancy, performance hard blockers, lifecycle, queue, paper execution and exit logic are unchanged.
- Historical replay also uses Primary-only confidence; Shadow remains informational.

No stop-loss, break-even, trailing, thesis/technical exit, target, EOD exit, sizing or queue behavior is changed.
