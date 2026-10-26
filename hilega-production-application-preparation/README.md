# Application preparation-route integration — stage and validate only

This package changes application source paths, rather than adding another isolated
controller prototype. It is NOT applied to the running application by these tools.
Production execution remains disabled. No real order transport is added.

## Concrete application changes

1. Installed controller Service gains guarded execution-route selection.
   Default SIMULATOR behavior remains the default. PREPARATION_ONLY requires an
   explicit future deployment configuration. Its selection is pinned in the
   workspace DB; changing the environment back cannot silently reinterpret it.
   Enrollment rejects any existing simulator intent/order/fill/reservation history.
2. The existing strategy-worker script selects the preparation source reader when
   configured for PREPARATION_ONLY. It rejects synthetic-price/fill funding options
   on that route and does NOT call the simulator bridge or SimBroker.place.
3. The source reader uses the existing hash-chain verifier and accepted-event
   classifier. First use baselines history. Only new, current-session, confirmed
   events from the pinned policy/version qualify. Arms, reconstructed rows and
   historical events cannot create preparation plans. Exits/reversals require
   separate real ownership/exit integration and are blocked here.
4. The source reader checks authoritative workspace Pause/version/session/stop,
   post-Resume signal freshness, current bridge lease and fresh signed evidence.
   Slow GET collection releases the control flock so Pause remains responsive.
   It rechecks admission afterward and again before commit.
5. A successful read-only evidence check commits the original signed evidence,
   source/event identity, evidence-bound plan, shadow hold, NON-EXECUTABLE outbox,
   consumed-event marker, source cursor and PAUSED control in one workspace SQLite
   transaction. It creates no simulator intent/order/fill or real broker receipt.
6. Existing Service Resume/reconciliation and direct simulator BUY calls are
   guarded against unresolved preparations and route bypass. Holds persist through
   restart/session rollover. No automatic deletion, Resume or release is added.
7. The authenticated workspace /status response includes application_preparation,
   and GET /api/hilega-production/execution-preparation exposes a safe summary.
   The existing control credential and same-origin protections are reused. No
   endpoint accepts caller-supplied evidence, account pins or order IDs.

The database owns the pending plan and source cursor, so losing a response after
commit cannot create another plan/hold for the same event. A precommit interruption
rolls back the complete preparation and cursor. A file lock serializes source
readers. Duplicate confirmed events remain consumed; blocked events are not retried
as new signals after Resume. Mutable local adapter scope/activity is rechecked
under a read transaction retained through the controller commit. This is NOT
atomicity with the remote broker or a distributed-transaction claim.

## Scope limits that remain

The hold is REAL_CASH_OBSERVED_SHADOW_ONLY, not a real cash reservation or debit
attribution. The outbox has request_body=null and
NON_EXECUTABLE_PRICING_POLICY_PENDING. Tick normalization/price protection remains
unverified, and no executable LIMIT/MARKET request is manufactured to bypass it.

The preparation route's reconciliation is explicitly a LOCAL baseline, never real
broker reconciliation. Real ownership, fills, positions, external/manual exits,
fees, global reservation accounting, daily loss controls and production readiness
remain unverified/pending. No real position or P&L is inserted into simulator UI
lists. The source worker can only prepare one unresolved plan before pausing.
An explicit reviewed recovery/cancellation workflow is still needed before reusing
a preparation workspace after a successful plan; no hold-release shortcut is added.

This package vendors the same VM-validated signed-evidence validator/GET-only
collector into a backend module and repins dependencies to the modified application
sources. It does not weaken account signatures, cash/market checks or thresholds.
Original standalone helper package sources used by the collector remain pinned.

## Ubuntu VM: create a separate staged application tree

Extract the ZIP into ~/RB-ITOS-AI. It adds only this package directory, containing
replacement source files under files/. Merely extracting/pulling the package does
NOT replace backend/scripts/tests in the running checkout.

From the repository root:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python hilega-production-application-preparation/stage.py \
  --stage /tmp/hilega-app-preparation-stage-v1
```

The stage directory must be fresh and outside the repository. The tool verifies
expected current application hashes, packaged hashes and pinned helper versions
before copying. If it stops on a mismatch, share the output; do not edit hashes.
It copies code/tests and required helper sources only, with no .env, credentials,
data directories or running application DB. There is NO --apply option.

Then run the staged application tests and selected installed regressions:

```bash
.venv/bin/python hilega-production-application-preparation/validate.py \
  --stage /tmp/hilega-app-preparation-stage-v1 \
  --report data/research/hilega-app-preparation-validation-v1.json
```

The validator uses the current VM venv interpreter, the staged backend as
PYTHONPATH, and runs:
- new application preparation integration tests;
- installed controller foundation tests;
- bridge health/background-watchdog tests;
- authenticated workspace API tests;
- existing strategy-to-simulator bridge regressions.

All evidence and strategy journal rows used by tests are synthetic. Credentials
are removed from the test subprocess environment; tests use fixture providers and
temporary databases. No installed service is started or restarted. The validator
writes a hash-bound PASS/FAIL report. A PASS does NOT apply or activate the changes.

Share the complete pytest summary and any failures. Do not run additional market
captures solely for this validation; the current after-hours/zero-cash blockers
cannot be cleared with synthetic substitutions.

Author checks: static diff review and Python AST syntax parsing only. No imports,
tests, demos, network/broker reads, source apply or services were run locally.

## Runtime configuration, for later deployment review only

Do NOT set these in the running app during staged validation:
- HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY
- the same explicit workspace DB path for API and source worker;
- HILEGA_PREPARATION_ADAPTER_DB: the closed pinned-account adapter DB;
- HILEGA_PREPARATION_PIN_FILE: existing private pin (default unchanged);
- either HILEGA_PREPARATION_EVIDENCE_FILE: a current owner-only signed bundle,
  or HILEGA_PREPARATION_CAPTURE_ON_SIGNAL=1 with existing local read credentials.

A file input is reverified for every signal; an old capture cannot authorize a new
session. On-signal capture reuses fixed GET-only endpoints with pin checks and
shell/.env conflict protection. It does not hold the control flock during network
reads. Slow collection or stale heartbeat/quotes remains a blocker; no stale-data
exception or automatic retry has been added. Broker-read scheduling/cadence still
needs operational validation before deployment. No private pin, token or key is
stored in the application plan. Stored signed account evidence is private data.

The existing worker identity/policy/version, shared control APIs and verified audit
source remain authoritative. There is no alternate UI arm flag or production LIVE
mode. The service still exposes SIMULATION_ONLY as its outer workspace/control
shell; preparation status explicitly distinguishes the route and remains disabled
for real execution. A future production execution shell still needs design/review.

## Exit criteria and next milestone

This step is complete only when the STAGED application tests and simulator/API
regressions pass. Then the source diff, staged validation and deployment/rollback
plan can be reviewed for a separately authorized no-order application deployment.
No deployment approval is being requested before that result exists.

After that, required work includes: actual market-hours preparation observations;
reviewed tick/pricing policy; real cash/reservation/risk integration; genuine
transport provenance and broker acknowledgement/fill/ownership reconciliation;
partial cancellation/external/manual exits; safe release; alerts/recovery/rollback;
and a separately authorized supervised minimum-size pilot after readiness gates.
