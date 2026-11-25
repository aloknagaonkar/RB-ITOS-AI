# Activate the validated three-minute observation strategy

This companion deploys the existing validated v2 source package and built frontend.
It does not replace v2 or rerun the November comparisons. It activates the agreed
3-minute any-2-of-3 rules in live-data observation. It does not arm a broker worker,
enable execution, change `.env`, change strike/risk enrollment, start either failed
execution service, or edit a database itself. Normal API/worker restart recovery
may update application state and audit journals.

## Additional integration fix

The outer live worker skips all ticks when `domain.in_session` returns false at
15:30. That would prevent the newly implemented 15:30 close from being called.
The rollout adds a small helper and patches ONLY the existing directional-branch
out-of-session guard. Other current VM worker source is preserved verbatim.
The patch checks the exact branch/guard and stops if their structure has changed.

After regular weekday session end, only the selected 3m alignment coordinator
can get a closing tick. It consumes only regular-session candles and cannot open
positions at/after 15:30. It retries late final-minute evidence until that day's
close is recorded, then stops further closing ticks. Other strategies and weekends
retain their existing behaviour. Fourteen focused VM test cases cover the close
boundary, delayed evidence/retries, completed-close idempotency, next-session
markers, legacy policy intervals, other strategy IDs and weekends.

This remains a strategy/option-shadow close, marked using the 15:29 close. It is
not a broker fill. Actual broker square-off timing/reconciliation is still not
validated or enabled by this rollout.

## Identified service scope

The script restarts only these services if they are currently active and their
WorkingDirectory matches the repository:

1. `hilega-api.service`
2. `hilega-lifecycle-reference.service`
3. `hilega-observation-analytics.service`
4. `hilega-observation-readiness.service`

The API and analytics services must already be active. The rollout leaves
`hilega-worker.service` and `hilega-production-source-worker.service` untouched,
and requires they are not active. System SQLite bridge services are untouched.
No user/system units are installed, edited or daemon-reloaded.

## Apply on the Ubuntu VM

Extract this ZIP in `~/RB-ITOS-AI`, then:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -B hilega-3m-live-rollout-v1/rollout.py --apply
```

The defaults point at the v2 stage and successful validation report already
reported in this conversation. The local API default is `http://127.0.0.1:8123`.
If that API address differs, pass the actual loopback API base using `--api-url`.

Before touching services it checks all v2 source/stage hashes, the successful
validation report, simulation workspace configuration, selected strategy, active
service scope, and local open/pending/uncertain sandbox ledger state. No sandbox
execution process may be active. It prepares and syntax-checks the scoped worker
patch in an isolated temporary backend, then runs the new worker-close tests
using the existing VM virtual environment. No tests are run during package creation.
For preflight/tests alone, use `--check` instead of `--apply`.

The original worker source is read from the CURRENT VM and backed up; the script
does not overwrite it with an old snapshot. The unchanged VM evidence helper and
cache writer are preserved by the validated v2 package. The verified v2 code is
copied exactly, with only the additional worker helper and scoped scheduling patch.

After the checks, it creates a timestamped source/frontend backup under
`data/deployments/hilega-3m-...`, stops the identified active services, rechecks
source/ledger state, copies the files and built frontend, and starts those same
services. It verifies the API version and a fresh PASS bootstrap from the actual
3m worker plus fresh `hilega: OK` component health. Startup progress is printed
every five seconds. The default timeout is 300 seconds; a slow warmup can use
`--startup-timeout 600` (maximum 900).

The live worker must be able to bootstrap against current-session data, including
credentials, caches and feed access. Deploy during the regular session or after
15:30 on a weekday when its closing path can run. Before the open or on a weekend,
fresh bootstrap verification will not complete and the rollout will restore the
old files rather than claim that live processing was verified.

Success is `LIVE_OBSERVATION_DEPLOYED`; share that result to review runtime status.
If startup or checks fail after services stop, the script restores source/assets
and starts the previously active services. `ROLLBACK_REQUIRES_ATTENTION` means
manual service attention is needed; share the printed receipt and error.
The script never clears positions, reconciles a broker account or deletes journals.

## Later source rollback

Use the EXACT backup directory printed by the successful deployment:

```bash
.venv/bin/python -B hilega-3m-live-rollout-v1/rollout.py \
  --rollback /absolute/path/from/deployment/receipt
```

Rollback checks installed-source/frontend hashes and local sandbox state, stops
the same services, restores their previous sources/frontend and restarts them.
It preserves all runtime databases, journals and newer audit evidence. It does
not pretend that source rollback reverses any runtime decisions or external fills.
