# Hilega closed application exit dispatch v1 — staged patch

This package stages the first application exit-dispatch step. It is NOT a live exit executor. The source now commits a durable REFUSED_CLOSED exit record with journal consumption, the paused controller and its audit entry in the same application transaction. It creates no SELL request. Live ownership/fill quantities remain unknown, and no automatic promotion of these records to executable orders is permitted.

## Validate first

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-exit-dispatch-closed-v1.zip \
  hilega-exit-dispatch-closed-tools-v1
.venv/bin/python \
  hilega-exit-dispatch-closed-tools-v1/run_tests.py --repo "$PWD"
```

The runner pins the deployed entry reservation source versions, builds a TEMPORARY import overlay containing the patched source.py and new exit_dispatch.py, runs 10 local SQLite transaction tests, then four new Source scenarios and the existing entry/application/adapter regressions. Installed source, configuration and running services are not changed. No production database migration or broker read is performed. A timestamped JSON report is saved beside this README.

The 10 transaction tests passed in the packaging environment. VM Source scenarios and regressions have not yet run against this patch. Do not deploy it until that validation is reviewed. There is intentionally no apply command in this package.

## Runtime changes staged

- source.py routes a verified EXIT boundary to dispatch_closed instead of recording only a generic block.
- exit_dispatch.py creates preparation_exit_dispatch lazily inside the exit transaction. Records contain the confirmed event, its fingerprint, the boundary fingerprints, provenance and an explicit refusal. No owned instrument/quantity or parent order is inferred.
- Restart/replay does not duplicate the record or audit; conflicting same-ID evidence blocks.
- Reversal boundaries consume both events and suppress new entry admission.
- Interrupted transactions leave no partial exit record, consumed event or cursor advance.
- Existing local cash reservations and broker adapter requests are untouched.

No historical exits are backfilled. Previously consumed records stay consumed. The live transport gate remains unconditionally closed. Existing reasons remain EXIT_OR_REVERSAL_REQUIRES_LIVE_OWNERSHIP, and the controller pauses as before.

## Boundaries and remaining work

A PASS proves the staged durable closed-dispatch path works in synthetic temporary databases. It does not prove live ownership, fill reconciliation, a complete exit order path, fee attribution, net P&L, broker cash locking or reservation release. Those remain pending. A future executor must use new authenticated current evidence and explicit admission; it must never automatically execute these historical refused records.

The entry policy remains a maximum 50% of verified available cash including buffer, with the existing one-lot limit. No daily loss limit is required. No production permission is enabled by this package.
