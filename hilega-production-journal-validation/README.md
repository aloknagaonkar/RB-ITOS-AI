# Recorded journal validation (isolated simulator only)

No installation/apply step. No service restart, .env access, network requests,
production orders, strategy edits or active simulator DB changes. Uses installed
health milestone modules with exact dependency hashes. Fails on unexpected code.

Run tests on your VM; these have NOT been executed in preparation. Only Python
AST syntax checks were performed. Tests use synthetic source fixtures; the CLI
uses your actual hash-verified recorded journal without rewriting events.

Run from repository root with PYTHONPATH=backend:. and a NEW output directory.
Use --date 2026-10-22 first. Historical records from before the currently installed
strategy version are deliberately rejected; they are not relabelled as current.
No eligible records or a version mismatch requires reviewing available evidence.
The default source is data/live-observation/hilega-directional-v1/step-audit.jsonl.
A saved copy of that exact hash-chained journal can be passed using --source.
The existing bridge's 64MiB journal limit applies.

Three separate databases/scenarios:
- ARMED: controlled synthetic operator resume before first selected boundary.
- PAUSED: no BUY is allowed for any recorded signal.
- RESUME_AFTER_FIRST_BLOCKED_ENTRY: block first entry, resume one second later,
  confirm duplicate old signal stays blocked and later eligible signals can enter.

The runner uses the installed accepted-event parser, event dispatcher, health
lease gate, simulator ledger and ownership reconciliation. Every event is
processed twice to verify idempotency. Reversal fills are checked SELL-before-BUY.
The actual live journal cursor/watch loop, browser UI and API watchdog are NOT
exercised by this runner; their existing tests remain separate.

Time is an isolated historical clock. Heartbeats, option prices (100), quantity
(65), fills and operator commands are synthetic. This does not measure NIFTY
performance, live order quality, real broker ownership or indicator calculation.
This is recorded-event dispatch validation, NOT fresh strategy/indicator replay.

Unmatched exit references or unsubmitted baseline entries produce REVIEW_REQUIRED,
not PASS. Full-session completeness is not inferred from the date. Reports retain
first/last boundary, verified journal chain tip and selected record counts.
Open positions are preserved and disclosed if the source stops before its exit;
no fake closing event is manufactured. Each scenario stops PAUSED.

summary.md prints a per-event table; each scenario/report.json includes original
signal names, qualified time, exit reason/reference, decisions and synthetic
orders/fills. The root report.json provides status and limitations.

Protect generated evidence outside public Git; do not upload credentials or .env.
