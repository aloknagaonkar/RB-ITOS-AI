# Isolated journal-reader iteration validation

No installation/apply step, env edits, API restart, active DB writes or broker
requests. The new package calls the installed Bridge.run_source_once against
separate copies of original hash-chained record prefixes. Original records and
hashes are retained; the actual source journal is read only.

Exact dependency hashes require the already-applied bridge-health milestone.
22 October current-version records are required. A mixed-version date is rejected.
Run tests first on the VM, then run.py --date 2026-10-22 --output NEW_DIRECTORY.
Default --source: data/live-observation/hilega-directional-v1/step-audit.jsonl.
Source file limit is the installed reader's 64 MiB. Each selected boundary advances
an isolated journal copy; repeated hashing can take time on a large source.

Scenarios:
1. Existing-history baseline: existing entries/exits never submit orders.
2. Armed historical polling: baseline prefix, append original records in order,
   verify cursor, repeated-read idempotency, ownership and exit matching.
3. Pause then resume: first entry blocked, old event never re-enters on Resume,
   later fresh entry allowed. Inject lost heartbeat while position open; pause
   without browser, preserve established position, recover without auto-resume,
   and allow the matching exit while paused.
4. Both iteration scenarios reconstruct Service/Bridge against the same isolated
   DB to verify durable cursor and paused restart. Fresh heartbeat with stale
   source blocks Resume. Truncation and tampering affect test copies only and
   must block without adding orders.

Recorded armed/candidate-only events are checked where present. If the source
contains none, no actual candidate coverage is claimed; synthetic unit fixtures
include that case. The day needs two eligible confirmed entries and a later
matching exit to exercise the pause/resume/health path; otherwise REVIEW_REQUIRED.

Synthetic prices (100), quantity (65), fills, historical clock, heartbeat freshness
and operator controls are test inputs. No NIFTY/option performance evaluation,
indicator replay, full-session coverage proof, browser/UI test or actual broker
reconciliation is performed. No claim of real process crash or OS subprocess
supervision: restart reconstruction and production reader iterations are tested;
the CLI --watch loop and real API watchdog are separate integration work.

The health fault is a direct call to the installed watchdog method without a
browser; API background scheduling is covered by the prior health test suite.
Reversal handling remains covered by prior synthetic tests, not invented recorded
reversals. Health and service state are separate from actual live strategy workers.

Output summary.md prints checks and signal decisions; per-scenario report.json
contains cursor, original event names, controls, synthetic orders/fills and errors.
A new output directory is required; reports/databases are private. Source copies
can contain operational evidence: keep generated output outside public Git.

Only Python AST syntax checked during preparation. No tests, replay, demos or
frontend builds have been run locally. Leave live journal opt-in disabled and
production execution false. No deployment is required for this research runner.
