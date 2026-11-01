# Exclusive Source / closed coordinator routing candidate

## Milestone and purpose

The previous VM checkpoint passed 172 combined coordinator cases. This package addresses the next integration issue: the existing Source and the coordinator must not independently consume the same fresh ENTRY. It stages the actual Source method and actual worker call site, adds a signed durable ownership record and serializes Source/coordinator polls on one private route lock.

This is a staged candidate, not a deployment. Behavioral tests must run on the VM. No local behavioral test pass is claimed.

## What changes in the staged copies

| Caller / state | Behavior |
| --- | --- |
| Unenrolled Source | Original preparation-only logic runs under the route lock |
| Enrolled Source called by a legacy poller | Returns CLOSED without changing the cursor or collecting evidence |
| Enrolled coordinator called directly | Returns CLOSED; exclusive route context is required |
| Enrolled coordinator through candidate_poll | Verifies signed owner and bindings, holds route lock, invokes existing coordinator |
| Nested Source EXIT dispatch during candidate_poll | Allowed only for the same Source, journal and owner context |
| Actual staged worker CLI | Uses closed_poll; never constructs an execution session |
| Missing/invalid owner record or changed lease/binding | Blocks; no automatic takeover or rebaseline |

The new route lock is separate from the controller lock, so slow evidence collection does not hold the controller flock. The lock surrounds the complete candidate poll. A ContextVar permits nested Source calls by that owner without reacquiring the same flock. Ownership stays durable across restarts. Different seed, journal, authority or bridge lease requires a separately reviewed migration; there is no release/takeover CLI.

Both Source and coordinator entry points are guarded. Protecting only the worker call site would leave a direct Source caller able to consume a signal. The tests include competing legacy/candidate polls, two candidate pollers, enrollment rollback, restart after committed BUY, tampered/deleted ownership, two complete cycles, and the actual staged worker main in --once mode with synthetic dependencies.

## Run on VM

Keep the prior expanded packages, including hilega-durable-coordinator-v1 with its corrected boundary helper and successful 172-case VM-VALIDATION.json. This runner checks exact baseline hashes, including the corrected test helper. Do not unzip the old coordinator ZIP over that corrected folder.

Targeted validation (19 expected cases):

```bash
.venv/bin/python hilega-exclusive-route-v1/apply_and_test.py --repo "$PWD"
```

After it passes, combined candidate integration (191 expected cases):

```bash
.venv/bin/python hilega-exclusive-route-v1/apply_and_test.py --repo "$PWD" --integration
```

The runner creates a new hilega-exclusive-route-stage-* directory containing a candidate Source, worker, coordinator and guard. pytest loads these modules only in its subprocess; installed files remain untouched. The tests use temporary synthetic databases and intercepted transport. The default CLI remains closed without application modules or credentials. The staged worker main test supplies temporary fixture objects and mocks dotenv/service health operations; it is not a real systemd start.

The stage remains available for review, with STAGED-MANIFEST.json. VM-VALIDATION.json is written in this package. The 191-case option is combined candidate integration, not full repository regression.

## Production boundary and pending work

No application sources are installed, no services are stopped/restarted and no production account is enrolled. The route API is Python candidate injection only. There is no configured execution session factory for the actual running worker. The installed code-level order gate stays closed; positive tests intercept transport explicitly. Enrollment in a test is not permission to trade.

Before deployment, review supervisor/configuration and dependency manifests, quiesce all old worker processes, stage a bounded startup/rollback plan, and prove actual service routing. An unpatched old process does not participate in the new guard. Cross-session/bridge-lease/state migrations also need explicit review. Tests do not prove exclusive routing in the currently running services.

Actual broker validation, trusted production authority/policies, complete fees/net P&L, cash-release handling and full release regression remain pending. Local reference retirement never claims broker cash release.
