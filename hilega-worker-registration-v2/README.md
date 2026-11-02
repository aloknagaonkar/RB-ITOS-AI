# Four-part closed worker registration package

Prepare on the VM:

    .venv/bin/python hilega-worker-registration-v2/apply_and_test.py --repo "$PWD" --integration

Requires the passing 276-case release-assembly report and retained release folder. Integration reruns those 276 cases, then twelve new tests: 288 total. Without --integration, twelve new tests run after the bounded health check. No behavioral tests were run in the packaging workspace.

Combined changes:

1. Stage explicit worker arguments --closed-registration and --closed-registration-sha256. The exact public JSON document supports only CLOSED_PREPARATION_ONLY, execution_factory_configured=false and production_execution_enabled=false. Default routing is preserved; no Source, Store, secret provisioning or execution session is created by registration loading. This is closed registration infrastructure, not positive execution factory activation.
2. Bind base/new release manifests, registration digest and tooling digest in a proposed approval document. Existing supervisor approval is retained; no new supervisor approval or service ExecStart is written.
3. Run a direct bounded registration/coordinator probe, then create PROBE-PLAN.json for an optional separate managed transient unit. The probe never constructs Source or Store and does not execute the real worker. Actual worker managed startup remains unverified.
4. Apply and restore the actual old/new worker bytes in a disposable rollback directory. Installed worker and live databases are untouched. Actual runtime/database rollback remains unverified.

The default prepare action does not issue service control commands. After reviewing the concrete PROBE-PLAN.json, a separately requested probe can be run with:

    .venv/bin/python hilega-worker-registration-v2/apply_and_test.py --repo "$PWD" --action probe --plan /absolute/review/PROBE-PLAN.json --approve-plan-sha256 EXACT_REPORTED_DIGEST

The optional probe starts only its unique hilega-closed-registration-probe-* transient user unit, bounded to 20 seconds with AF_UNIX-only sockets. It does not stop/restart/install any application service. Failure is reported for review; no settings or pins are bypassed.

No live apply is available. Full service dependency closure, execution registration/authority, new supervisor approvals and companion pins, real managed worker startup/rollback, full regression, broker validation, fees/cash/partial-fill policy, fresh-seed enrollment and controlled live authorization remain separate requirements.

V2 corrects a packaging defect: the bundle omitted market_lab/__init__.py, allowing another regular installed market_lab package to take precedence over the bundled namespace directory. The reviewed inert initializer is now included and hash-bound, the probe verifies its registration module came from the bundle, and failure stderr is retained. Two added regressions cover competing-package resolution and package-boundary collision. V1 files, failed reviews and installed code remain unchanged.
