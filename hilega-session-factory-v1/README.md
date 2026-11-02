# Execution-session factory candidate and corrected post-deploy checkpoint

## Milestone

The actual closed preparation hook is installed and managed startup passed. The follow-up observation confirmed an advancing RUNNING heartbeat on the same lease. Live execution remains disabled and no execution candidate is enrolled.

This package combines two related tasks:

* Capture a proper POST-DEPLOYMENT-BOUNDED.json using up to 30 seconds for heartbeat advancement instead of a fixed six-second window. The earlier report is retained.
* Stage an execution-session factory and its actual worker call site, with ten candidate tests. The running worker is not replaced.

## VM command

```bash
.venv/bin/python hilega-session-factory-v1/apply_and_test.py --repo "$PWD"
```

This first checks the current real closed deployment read-only. It then stages candidate files and runs ten tests using temporary synthetic databases and intercepted transport. The 212-case checkpoint is retained. Optional combined candidate integration expects 222 overlapping cases:

```bash
.venv/bin/python hilega-session-factory-v1/apply_and_test.py --repo "$PWD" --integration
```

No behavioral tests ran in the assistant workspace; syntax checks only. Do not run old pre-deployment apply scripts to adjust their source pins: this runner explicitly derives the three post-deployment hashes from the exact approved rollout plan and checks the other original pins unchanged.

## Factory behavior

The default worker call uses the existing closed preparation route. No context loader is registered through environment variables, CLI flags or dynamic module names. A factory must be explicitly injected in Python.

Even when injected, the installed require_live_clearance gate executes before context loading, authority/provider access or session assembly. This gate remains closed. Positive tests explicitly intercept it and intercept order transport. After the gate, the factory validates the exact context shape, existing adapter/pin/independent authority, Source identity, journal and bridge lease. It constructs the existing CandidateSession and delegates through signed exclusive-route ownership. No automatic route enrollment or arbitrary seed adoption occurs.

The cache is bound to one Source and journal. Existing coordinator recovery is reused, including committed-attempt recovery without repeated evidence capture or send. Tests cover two complete synthetic cycles through the factory, default closed preparation, real gate, environment non-activation, invalid context/lease, missing owner and restart recovery.

## What remains pending

This is the factory assembly/call-site candidate, not a configured production credential/provider loader. The explicit context loader remains supplied by tests; no private authority files are opened by it. The actual running worker still has its previous closed hook. Production factory provisioning, initial seed/ownership enrollment, policy approval, complete dependency reconciliation, broker validation, fees/cash handling, full release regression and eventual controlled live validation remain pending.

The private stage contains candidate worker, Source, coordinator, guard and factory files. No services are stopped/restarted, no approvals rewritten, no account capture requested by the checkpoint, and no installed sources changed. A failed checkpoint reports evidence without automatic recovery. Production execution/readiness stay false.
