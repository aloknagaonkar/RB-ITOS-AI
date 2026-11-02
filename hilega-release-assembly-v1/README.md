# Candidate release assembly and closed rehearsal

On the VM:

    .venv/bin/python hilega-release-assembly-v1/apply_and_test.py --repo "$PWD" --integration

Requires the passing 268-case lock report and retained review folder/wheel. Integration reruns those 268 cases using the already retained wheel (no new download), then eight new assembly tests: 276 total. Without --integration, only eight new tests run after a bounded running-health check. Do not discard old review folders.

The new release folder contains the reviewed candidate graph's Python modules, fixed dynamic targets at their expected relative paths, dependency metadata, worker candidate, and locked wheel. Conflicting paths or changed inputs block assembly. A manifest binds all bundle files. A clean-environment closed coordinator CLI is run twice with no session injection, secrets or application database access. A disposable file apply/restore is rehearsed.

Existing supervisor approval bindings are reviewed using the previously reviewed read-only code. Configuration values are not exported. Existing approval is not treated as approval of this release. No approval files are written, and no service commands or live database changes are issued. No runtime registration is installed. There is no apply action.

The bundle covers the explicit candidate import graph, not all API/worker/service dependencies. Tests do not prove actual managed startup, worker factory registration, release approval reconciliation or live rollback. Those remain explicit blockers, along with full regression, trusted authority, broker validation, policy/fee/cash decisions and fresh-seed enrollment. Production execution stays disabled.
