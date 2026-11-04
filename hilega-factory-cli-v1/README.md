# Exact outer CLI — combined synthetic factory lifecycle qualification

This package tests the **same passed factory candidate**, unchanged, through its bundled launcher and outer watch loop. It adds validation, not another runtime implementation or deployment.

## Single VM command

```bash
cd ~/RB-ITOS-AI
unzip hilega-factory-cli-v1.zip
.venv/bin/python hilega-factory-cli-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-d_l5gg3t/PLAN.json" \
  --current-plan-sha256 86e185662e51e325abae7a24e06ea074f1a01afa0476e135c1fe19a5504dceac \
  --factory-review "$PWD/hilega-factory-process-review-r0xboscg"
```

Uses existing venv/pytest, user systemd, prior packages and the applied bootstrap deployment plan. Checks installed status using bootstrap-deploy v1 before and after. No packages installed and no broker requests.

## What the 32-case batch covers

The earlier 30 registered-factory/file/lease/seed cases are reexecuted, plus two outer CLI cases:

1. A forked worker process runs the exact bundled launcher/watch loop from an empty synthetic workspace. Native startup claims a lease. With the gate still closed, native reconcile/resume is followed by a fresh synthetic confirmed signal and a disabled preparation. Signed local bootstrap creates the synthetic context/owner. Only then does the test enable its in-memory gate override and fixture registration provider, permitting two full factory cycles and four intercepted sends. Normal CLI termination runs native `finish` and leaves the controller paused. A second, distinct process claims a new lease; old authority must fail closed without sending or creating a new request.
2. Another fresh outer CLI flow rotates its synthetic signing-root file after the first intercepted BUY. Cached-session validation must reject it, stop with pause and issue no second send.

The restart check certifies **pause/rejection**, not automatic recovery or migration of trading authority to a new lease. No replayed BUY is allowed.

## Explicit test substitutions

- Synthetic clock and loop cadence; the between-poll driver supplies signals/fills and advances the fixture clock.
- The registration-file location is redirected to a private synthetic file. The original registration parser, file permission and hash checks still run. The sealed release's disabled registration is unchanged. This does not qualify a production registration-activation mechanism.
- Market/account evidence providers and transport check/send are synthetic/intercepted.
- `require_live_clearance` is overridden only inside each child after signed disabled bootstrap; bootstrap itself uses the real closed-gate behavior. The parent gate remains closed and gate source bytes stay unchanged.
- Native lease claim, outer heartbeat/watch, factory dispatch and finish/pause functions run; fixture hooks observe claim/poll results and provide safe diagnostic labels.

All databases, keys, credentials and signals used for the tests are synthetic. Python socket hooks and the systemd Unix-only address-family restriction deny real network calls. One-position policy remains unchanged.

## Results and remaining boundary

Creates `hilega-factory-cli-review-*` with `TESTS.xml`, `MANAGED-PROCESS.json`, before/after status, `INPUTS.json`, `RESULT.json` and `MILESTONES.md`. Synthetic workspace logs include `CLI-ADMITTED.log`, `CLI-RESTART.log`, result files and, on failure, `CLI-LAST-ERROR.json` / child traceback. No success receipt is issued if any of the 32 cases fails or skips.

A pass qualifies the synthetic outer factory lifecycle under these stated substitutions. It does not provision real trust, activate production registration, implement automatic authority rebinding, verify an actual reboot or validate real order transport. Broker timestamp semantics, fees, ownership, real enrollment and final activation remain unfinished. No live changes or apply command are included.

Behavior tests are VM-only. Development-host verification is syntax/AST, pinned-source anchors and ZIP integrity only.
