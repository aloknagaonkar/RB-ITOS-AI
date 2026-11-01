# Durable closed application coordinator candidate

Previous checkpoint: 147 VM integration cases passed for second application cycle V3. This bundle is new and has NOT been behaviorally tested in the assistant workspace. Run the tests on the VM.

## Why this change is required

The existing candidates validate actions individually. A polling worker must also remember which action is due and recover when an action commits but its worker state update is lost. This isolated coordinator persists a signed phase, journal prefix and current request, then invokes those existing APIs. It never creates another order to resolve an unknown outcome.

| Phase | Action | Next phase |
| --- | --- | --- |
| BUY_PENDING | Adopt the explicit prepared request | ENTRY_REVIEW or ENTRY_UNKNOWN |
| ENTRY_REVIEW | Reconcile signed complete BUY fills | WAIT_EXIT; partial BUY stays held |
| WAIT_EXIT | Let actual Source record the closed EXIT boundary | SELL_PENDING |
| SELL_PENDING | Invoke existing scoped SELL candidate | EXIT_REVIEW or EXIT_UNKNOWN |
| EXIT_REVIEW | Reconcile fills; retain working or residual quantities | CLOSEOUT_PENDING when flat |
| CLOSEOUT_PENDING | Record gross closeout without fabricating fees | RETIRE_PENDING |
| RETIRE_PENDING | Archive and retire local references | WAIT_NEXT |
| WAIT_NEXT | Require explicit Resume and a new eligible confirmed ENTRY | PREPARE_PENDING |
| PREPARE_PENDING | Create a disabled request using cached signed evidence | BUY_PENDING |

The Python CandidateSession interface is used only under intercepted transport in tests. The default CLI has no session injection option: `--once` and `--watch` always return CLOSED without loading application modules, credentials or databases. Environment variables do not enable it.

## VM validation

Keep the three existing expanded folders in the repository: hilega-application-cycle-close-v1, hilega-history-aware-preparation-v1 and hilega-second-application-cycle-v3. The V3 VM-VALIDATION.json must contain the successful combined 147-case report. Existing packages and pinned installed sources are checked before and after validation.

Fast targeted run (25 cases):

```bash
.venv/bin/python hilega-durable-coordinator-v1/apply_and_test.py --repo "$PWD"
```

Combined candidate integration (172 expected cases):

```bash
.venv/bin/python hilega-durable-coordinator-v1/apply_and_test.py --repo "$PWD" --integration
```

These are candidate integration checks, not the full repository regression. The runner creates temporary synthetic databases through existing pytest fixtures. It does not install sources, open live application databases, read private configuration, start services or send broker orders.

## Recovery and boundaries

A private flock serializes candidate pollers. Signed coordinator state binds the application, broker database, journal, seed request, bridge lease, authority identity and coordinator source hash. Missing state rows are not automatically recreated. Journal prefix changes block processing. Each existing action commits before the coordinator advances; if interrupted, the next tick invokes that action's existing idempotent recovery. Next-preparation inputs are stored before admission so recovery can use identical evidence after the admission commit.

The coordinator uses the original first-cycle APIs for the seed and scoped V3 APIs for subsequent cycles. worker_history_preparation_v1.py is an isolated copy of the prior preparation candidate using V3 multi-archive attribution. Previous package files are unchanged. Original full signed account captures stay intact.

Unknown BUY/SELL outcomes remain held. Working partial exits and cancelled residual exposure do not cause automatic replacement orders. An EXIT-first reversal does not immediately buy the opposite direction. A later fresh single ENTRY and explicit Resume are required. In the flat phase stale/pre-Resume records are consumed with a signed transition audit and no order; they are never replayed later as fresh signals.

## Still pending

This is NOT an installed automatic execution worker. Routing ownership between the running Source and coordinator must be reviewed and staged before deployment; the current candidate assumes one owner of the entry-routing decision. Cross-session baseline/lease migration and signed state upgrade migrations are not implemented. The actual hard gate remains closed before candidate state/capture access, including during recovery unless the test explicitly intercepts the gate.

Production authority/policies, actual broker validation, full dependency reconciliation, complete fee/net P&L and broker cash release remain incomplete. Local reference retirement is not broker cash release. No application branch merge, service installation, deployment or production enablement is included.
