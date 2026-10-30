# Entry reservation maintenance deployment v1

Deploys only the previously VM-tested reservation integration package whose
manifest SHA256 is 5800f8c5690b7750e1eed3846cc38a4845a42e07112ddf1e20aa058d48acf553.
Requires the existing hilega-entry-reservation-integration-tools-v1 directory and
its PASS regression report (14 unit tests and the supplied application regression).
No new runtime patch is generated here.

## Commands from ~/RB-ITOS-AI
    .venv/bin/python -m unittest discover -s hilega-entry-reservation-maintenance-tools-v1 -p 'test_maintain.py' -v
    .venv/bin/python hilega-entry-reservation-maintenance-tools-v1/maintain.py check --repo "$PWD"
    .venv/bin/python -u hilega-entry-reservation-maintenance-tools-v1/maintain.py apply --repo "$PWD"

Use && between these commands so a failure prevents the next action.
check is read-only. apply performs the authorized paused maintenance operation.
After success, optional read-only verification:
    .venv/bin/python hilega-entry-reservation-maintenance-tools-v1/maintain.py verify --repo "$PWD"

Do not rerun apply after STOPPED_FOR_REVIEW. Preserve its backup/transaction path
and share only the printed diagnostic. There is no automatic retry or rollback
while services might be running. A failed file replacement before restart
restores already replaced originals and removes a newly written target.

## Preflight
- Pin integration manifest, packaged code and installed baseline.
- Require the latest matching VM regression report to pass.
- Pin the read-only managed process inventory helper.
- Match all three user systemd services to their managed process identities.
- Require the existing paused safety checker to pass with journal caught up.
- Require empty application preparation/execution, adapter request/attempt/receipt
  and local reservation/binding tables, with no unhandled stop.
- Require PREPARATION_ONLY control, PAUSED, closed adapter and API execution disabled.
- Stale strategy source after the entry window is allowed only when the existing
  paused checker declares the worker operational; stale source is not entry approval.

## Apply
Creates a private backup under backups/hilega-entry-reservation-maintenance-*,
then stops exactly:
- hilega-worker.service
- hilega-api.service
- hilega-production-source-worker.service

Unrelated shadow/observer/publisher processes are not signalled.
Verifies those units are inactive with MainPID=0 and no detached application
process remains. Rechecks code and database activity before replacement.

Backs up/replaces exactly:
- backend/market_lab/hilega_preparation_runtime_v1/atomic_binding.py
- backend/market_lab/hilega_preparation_runtime_v1/cash_reservation.py (new)
- check-preparation-paused.py

No .env, credentials, startup-private settings, systemd unit or strategy-rule
configuration is changed. The code deployer does not migrate or write the trading
databases. Normal service startup still writes its usual control/heartbeat events.

Starts worker, API, source in that order, then verifies new managed identities,
updates only the saved maintenance children/PID metadata used by the paused
checker, and checks API health, empty activity and paused/closed control again.
The original identity metadata is backed up once and retained on verification
retries. No Resume/arming command is called. Source identity metadata is local
operational state, not account ownership or broker evidence.

Expected final status: ENTRY_RESERVATION_DEPLOYED_PAUSED_VERIFIED.

## Policy and readiness
The running code will add local reservation with a future eligible, funded,
unsent preparation. It does not create a reservation during deployment.
Entry remains capped at half verified available cash including buffer, one lot,
with no mandatory daily-loss limit. No broker cash is locked and no release
authority is added. Closed production transport is unchanged.

Older standalone inspection packages that pin atomic_binding.py will refuse the
new version until a reviewed pin refresh; their pins are not weakened here.
Actual fresh funded signal admission, broker ownership/debit attribution, complete
fees/net P&L, live lifecycle/recovery and controlled pilot remain unverified.

## Validation
22 local maintenance tests passed with ResourceWarning treated as an error.
Tests use temporary files/databases and mocked service commands/inventory. They
do not stop any actual service. Live VM maintenance is pending.
