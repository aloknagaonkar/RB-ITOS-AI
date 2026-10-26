# Multi-cycle reconciliation for the closed-gate consolidated port

Staged update to the installed closed-port library. OFFLINE FIXTURE routing only.
No live broker routing, production activation, real cash or strategy changes.
The active workspace execution route remains the existing simulator.

## Changes

- The port controller recognizes a settled prior broker fixture from an exact
  release receipt, settlement projection, matching zero hold and fresh ownership
  source. It does not rewrite SimBroker fills or pretend UNKNOWN intent rows are
  ordinary simulator orders.
- After verified flat/release, explicit Resume permits a later fresh signal and
  another cycle. A pending order/exit, unknown acceptance, missing receipt,
  nonzero owned quantity or stale/mismatched evidence blocks the next cycle.
- Restart/recover creates a durable evidence generation. Previously saved
  receipts or an idempotent replay of the old snapshot cannot authorize Resume;
  a NEW reconciled snapshot at/after recovery is required.
- Evidence refresh and release never automatically Resume or open another trade.
  Opposite-direction entry requires completed exit/release, explicit Resume and
  a post-Resume signal. Automatic reversal scheduling is not implemented here.
- Stale ownership at entry and rejected ownership evidence durably pause the port.
- Availability reports version closed-port-1.1.0-multicycle-fixture and flags
  multi_cycle_offline_supported=true, restart_requires_new_evidence=true.

The existing simulator/reader/UI controls still use their previous execution
route. The new behavior is in the consolidated library's isolated fixture API.
This does NOT establish multi-cycle real Upstox execution or live ownership.

## Stage and validate on VM

```bash
cd ~/RB-ITOS-AI
set +e
.venv/bin/python hilega-production-multicycle-port/install.py \
  --stage data/research/hilega-multicycle-port-stage
```

After STAGED:

```bash
.venv/bin/python -u hilega-production-multicycle-port/validate.py \
  --stage data/research/hilega-multicycle-port-stage \
  --output data/research/hilega-multicycle-port-validation.json
result=$?
echo "Validation exit code: $result"
```

Validation includes the new multi-cycle suite, consolidated adapter/port tests,
existing workspace/controls/allocation/ownership/health/strategy regressions, five
synthetic demos and staged frontend build. It runs in the stage with broker
observation and reader disabled and inherited secrets removed. No services start.
Source authoring verification was Python AST parsing only; VM execution is pending.

The former test requiring permanent legacy Resume rejection after settlement is
updated to assert PAUSED until explicit Resume after verified settlement. Its
safety behavior remains covered by pending/stale/missing-proof and recovery tests.
Other previously corrected tests are preserved. All source hashes are guarded.
Share mismatches/failures instead of changing manifest hashes to bypass them.
Use fresh stage and report paths for a rerun.

## Apply after PASS only

```bash
.venv/bin/python hilega-production-multicycle-port/install.py --apply \
  --validation data/research/hilega-multicycle-port-validation.json
```

Apply requires optional simulator reader disabled, simulator PAUSED and flat,
no pending/unknown orders and no held allocations. It backs up replaced files and
records created files in rollback.json. It does not modify the active simulator
DB, environment, strategy or service state. After APPLIED use the existing
frontend build and safe UI/API restart; do not restart strategy workers.

Keep the reported backup for rollback. Restore replaced files/remove only listed
created files while reader disabled and simulator flat/paused, then rebuild and
safely restart UI/API. New evidence-generation metadata exists only inside the
isolated port databases; opening older port fixtures forces new evidence and Pause.

## Remaining production gates

Actual production broker routing and automatic-reversal contract; verified real
receipt/fill/position ownership and external/manual exits; real cash reservation/
debit accounting (current actual NO_CASH_CAPACITY remains blocked); current
contract/quote/feed/risk gates including an explicit daily loss limit; live P&L;
readiness/alerts/backup/rollback; market-hours shadow observation; separately
authorized controlled pilot. The HTTP mutation gate remains closed in code.
