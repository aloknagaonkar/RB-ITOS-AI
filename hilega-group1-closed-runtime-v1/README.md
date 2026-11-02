# Group 1 — closed runtime deployment preparation

One runner and one STATUS.json combine worker import assembly, actual worker disposable startup/restart, supervisor review, managed rehearsal planning and deployment/rollback requirements.

Quick VM validation (recommended first):

    .venv/bin/python hilega-group1-closed-runtime-v1/manage.py --repo "$PWD"

Requires the passing 288-case registration V2 report plus MANAGED_CLOSED_PROBE_PASS in its retained review folder. Quick mode rechecks running closed health, assembles missing source-worker imports, runs the actual registered candidate worker twice against new disposable state, and runs eight new tests. No prior regression is repeated.

At the group checkpoint, --integration reruns the previous 288 plus eight new tests: 296 total. No behavioral tests are run in the packaging workspace.

The disposable worker uses an empty journal, empty env file and explicit SIMULATION_ONLY/PREPARATION_ONLY environment; no broker credentials are supplied. It creates only a new temporary application database, remains paused, checks zero orders/fills/preparations, never opens the adapter path, and verifies a new lease on restart. This does not verify fresh-signal admission or positive execution paths.

Default preparation issues no application service control commands. It writes a MANAGED-REHEARSAL-PLAN.json with exact manifest and tool hashes. After reviewing that concrete plan, the optional action is:

    .venv/bin/python hilega-group1-closed-runtime-v1/manage.py --repo "$PWD" --action managed-rehearse --plan /absolute/review/MANAGED-REHEARSAL-PLAN.json --approve-plan-sha256 EXACT_REPORTED_DIGEST

That action starts only a unique hilega-group1-worker-rehearsal-* transient systemd user unit, bounded to 55 seconds with AF_UNIX-only sockets. The unit runs the actual candidate worker against new disposable databases twice. It does not stop or replace the running source worker. Live application/adapter databases are used only by the existing read-only health checkpoint, never by the rehearsal.

DEPLOYMENT-PROPOSAL.json binds the installed worker hash, assembled release digest, existing supervisor findings and required backup/rollback rules. It is not an approved production change plan. No live apply action exists. Full API/worker/service dependency reconciliation, exact install/wrapper review, new supervisor/companion approval bindings, full regression, service quiescence and real backups remain required before actual deployment. Live database backups must never be automatically rewound.

Group 1 stays incomplete until the actual reviewed closed deployment/startup/rollback is verified. Group 2 (broker/authority/policies/fees/cash) and Group 3 (full live-release checks, approved enrollment and controlled pilot) remain pending. This package does not enable execution, resume the controller or enroll an owner.
