# Bounded preparation-session rejection test

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
