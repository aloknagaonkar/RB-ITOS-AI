# Bounded preparation-session rejection test v3

Scope: observe a newly confirmed ENTRY being rejected for zero cash on the existing PREPARATION_ONLY route. Does not open order transport or implement live trading. Defaults do not arm the controller.

## First VM step

From ~/RB-ITOS-AI, run unit tests and then `session_test.py check`. This reads application/account state, captures signed GET-only evidence, checks deployed release hashes, and writes a private report. It performs no reconcile, Resume or Pause command and creates no timer. It requires today's healthy source and market session, zero cash, no broker activity and no unresolved application/adapter activity.

No service installation, application file replacement, token update, controller arming or trading activation is part of this package.

## Run mode is a separate operation

Do not use `run` until the VM tests/preflight have passed, the operator has actually compared available cash with the pinned Upstox account display, and the bounded PREPARATION_ONLY admission test is explicitly authorized. It requires both `--confirm-upstox-zero-cash` and `--arm-preparation-only`; generic “go ahead” does not establish the cash-display fact. Do not set either flag just to bypass a rejection.

Duration is 60–600 seconds, default 300. The test must fit before the entry cutoff with a one-minute margin. A late or absent eligible entry is inconclusive. The source may pause on an unrelated exit/reversal first; that is not a zero-cash test pass. Do not replay an old journal event into the running application.

Run mode schedules an independent user-systemd pause timer BEFORE a single Resume attempt. It uses a copied helper in the private report folder. The timer makes a local Pause request, retries a failed safety request within configured service limits, and checks PAUSED. The terminal process also attempts Pause in cleanup. It never retries Resume after rejection, timeout or uncertain acknowledgement. Timer cancellation occurs only after PAUSED verification. Confirmed pause and the resulting zero-activity checks remain the acceptance evidence; the timer alone is not proof of success. API/authentication/host outages can prevent pause confirmation and require operator review. SIGKILL/power loss can prevent the terminal's cleanup; retained timer and attempt records support recovery.

Live systemd timer/controller integration has not been exercised by the local unit suite. Those tests cover injected orchestration and guards. Check mode does not exercise timer creation or Resume.

## Result interpretation

`ZERO_CASH_REJECTION_OBSERVED` requires one new consumed ENTRY linked to the verified journal after Resume, one new cash-only rejection audit, zero application/adapter activity, and verified PAUSED cleanup. It does not establish successful funded admission, real cash reservation, signed per-entry snapshot retention, tick/pricing approval, fill ownership, live exits, reconciliation or production readiness.

The saved preflight snapshot is not proof that the strategy used that snapshot at a later signal. The runtime must collect its own fresh evidence on the signal; this harness observes durable event/rejection linkage and does not replace that provider.

Reports and evidence go into a private `data/research/hilega-preparation-session-test-*` folder. Do not upload evidence, account snapshots, private config or credentials. Share only the printed summary. Preserve resume-attempt.json, resume-ack.json and deadline records on uncertain outcomes. Never delete plans/holds/requests to make a check pass.

Any new funds, position, order, request, hold or authority change aborts the zero-cash test for review. The harness never deposits funds, submits Upstox orders, exits positions, releases reservations or auto-resumes.

## v2 correction

Parses the command API envelope as `result.status.control` rather than assuming a top-level `status`. Validates the Resume acknowledgement request ID, action, control version, session and timezone-aware timestamp. The snapshot projection cannot stand in for the command acknowledgement. The first v1 run stopped on a KeyError and verified PAUSED cleanup; retain that report. This correction does not replay its Resume or change application/runtime files. A subsequent operator-authorized run uses fresh preflight and new command IDs.

## v3 dashboard cadence correction

The broker observer sleeps 30 seconds after collection and timestamps snapshots at collection start. An otherwise healthy dashboard snapshot can therefore briefly exceed the harness’s strict 30-second evidence limit. That limit remains unchanged. Only when the age check is the failing guard, the harness performs a fresh GET-only account observation using the same token resolution, verifies the account pin before and after, retains a private sanitized observation, and applies every original check again. It does not rewrite the server cache, change its 90-second UI display policy, change observer cadence, or change strategy quote/cash evidence collection. Authentication errors, unsuccessful checks, nonzero cash, any activity, unhealthy source, future timestamps, or direct evidence older than 30 seconds still block. The test report identifies direct refreshes. Additional broker reads are bounded by the session; a failed read stops rather than falling back to stale values.

The v2 run stopped with BROKER_OBSERVATION_STALE and pause_verified=true. Preserve that report and the earlier v1 report. No live-signal negative-test pass has yet been established.

Fresh direct observations may be reused for at most 10 seconds to avoid repeated GET bursts; their original timestamps are retained and their actual age recalculated. The dashboard cache is still not modified.
