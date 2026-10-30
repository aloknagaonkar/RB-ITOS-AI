# Hilega application lifecycle rehearsal v1

Run after the entry reservation deployment has been verified. This package is a test harness, not a deployment or activation patch.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-application-lifecycle-rehearsal-v1.zip \
  hilega-application-lifecycle-rehearsal-tools-v1
.venv/bin/python \
  hilega-application-lifecycle-rehearsal-tools-v1/run_rehearsal.py --repo "$PWD"
```

The runner checks package hashes and the expected deployed source versions. A mismatch stops the run; do not change the expected hashes merely to bypass it. It uses your existing pytest environment and repository synthetic fixtures. It writes a timestamped JSON result next to this README.

## What is exercised

Six new application scenarios use the installed Source and Service with temporary application and closed-adapter databases, synthetic signed evidence and an explicit FIXTURE account scope:

1. Admit a synthetic confirmed entry, commit the local 50% cash reservation and disabled request, then hand the unchanged request to a separate fake-execution database. Exercise fake fills, a staged exit reference, disabled SELL, fake acknowledgement, full exit, explicit zero-position evidence and gross P&L.
2. Partial exit followed by cancellation retains remaining exposure and the application reservation.
3. Lost exit response is not resubmitted and retains the reservation.
4. An unrelated order is rejected rather than adopted.
5. Reopening the application source does not duplicate the committed entry.
6. Manual live flatten remains blocked on the preparation route.

The original application adapter stays LIVE_CLOSED and byte-identical during fixture execution. Only synthetic data crosses the explicit fixture handoff; real-account scope is rejected. The application's reservation remains retained even when the separate fixture proves flat. No fixture execution is imported into the application.

The package also includes 204 component tests for the earlier reference, exit, gross P&L and handoff stages. Those passed locally during packaging. The six installed-application scenarios require the VM repository and have not been executed in the packaging environment.

## Policy and limits

Entry allocation remains at most 50% of verified available trading cash including the buffer, with the existing one-lot limit. No daily loss limit is required.

This does not read credentials, query Upstox, modify running services, migrate production databases, resume the running controller or send orders. Synthetic timestamps are fixed fixture timestamps; after-hours source staleness does not prevent the rehearsal.

A passing result is offline evidence only. Live application exit dispatch, authenticated ownership and fee/net P&L evidence, live fill reconciliation, controlled reservation release and a controlled broker pilot remain pending. The provisional fee buffer is not approved as complete live fee attribution. Production execution remains closed in code.
