# Combined candidate provisioning, enrollment and recovery workflow

Current evidence: 236 private-context/factory/lifecycle integration cases passed. The actual worker is running the closed preparation hook, controller PAUSED, and the inspected application/adapter have no active preparation or order activity.

## Combined work

* Read-only actual enrollment preflight, explicitly reporting WAITING_FOR_FRESH_DISABLED_PREPARATION when no first seed exists.
* Gated workflow API for staging private account pin, independent local candidate authority, broker token and bound private config without overwriting existing files.
* Signed route-owner commit after a fresh, unsent, signed first preparation has been verified; the lifecycle/control binding and freshness are rechecked in the same attached transaction immediately before commit.
* Durable private intent before database enrollment, plus recovery of a committed owner when the final receipt is interrupted, using the same identity files and no new key/enrollment.
* Candidate deployment contract showing required runtime bootstrap, trusted authority, fresh-seed and release prerequisites.

## VM command

```bash
.venv/bin/python hilega-provisioning-workflow-v1/apply_and_test.py --repo "$PWD"
```

Expected: passing bounded closed-deployment checkpoint and ten synthetic workflow tests. The default actual preflight should currently say WAITING_FOR_FRESH_DISABLED_PREPARATION. That is a prerequisite, not a failed test or permission to create a seed.

Optional combined candidate integration, expected 246 overlapping cases:

```bash
.venv/bin/python hilega-provisioning-workflow-v1/apply_and_test.py --repo "$PWD" --integration
```

All provisioning, key generation, private-file writes and owner commits in these tests use temporary synthetic fixtures. The runner does not provision real keys/tokens, enroll the live application, Resume the strategy, replace the running worker or make broker requests. No behavioral tests ran in the assistant workspace; syntax checks only.

## Transaction and recovery contract

The real installed order gate precedes every provisioning/recovery API operation. Tests explicitly intercept it. Preflight requires the exact guarded Source, existing closed Store/account, a complete validated pin, single first-cycle unsent BUY, fresh signed evidence, current source lease, correct journal/binding, controller's preparation pause and no pending stop. The entry clock and 60-second signal/draft bounds are retained. No historical, missing, invented or stale seed is adopted.

The shared route lock serializes patched Source/coordinator activity during provisioning. New files are staged in a fresh owner-only directory and fsynced before owner enrollment. A local random candidate authority key is separate from the capture key. This is not externally trusted production authority or a broker permission grant.

Enrollment uses the existing signed owner schema/binding/verification inside the proven attached application/adapter transaction. It sends no order and changes no broker request. Failure before commit rolls the owner back; private intent files are retained for review. Failure after commit retains the same private identity material so recovery can verify the existing owner without new key generation. Files and database are not claimed to be a single filesystem/SQLite atomic transaction. Recovery requires the same reviewed config digest and valid context; expired-context recovery remains a separate pending policy.

No live provisioning/enrollment CLI action is exposed. The workflow API remains gated and candidate-only. Its default deployment-contract report is not an approval to clear that gate.

## Actual deployment prerequisites still pending

The running application has no fresh disabled first-entry seed now. Do not Resume or manufacture one solely to clear this report. Future initial enrollment must be scheduled with an explicitly approved fresh-signal/bootstrap workflow; signal/evidence expiry must not be bypassed while waiting for approval.

Runtime bootstrap registration/dependency closure, trusted production authority/policy approval, broker/account/network validation, approved private-context digest registration, full release regression and reviewed closed deployment are not installed by this package. The coordinator still requires explicit Resume eligibility for later entries. Fees/cash handling and controlled live validation remain pending. Production execution/readiness stay false.
