# Group 2 — GET-only broker evidence and readiness candidates

This package uses the completed Group 1 cache-recovery receipt to locate the current active closed plan. It validates current deployed status before work, runs twelve new candidate tests and discovers only the lifecycle-reference service's explicit pin/env paths. It does not install code, control application services, resume, enroll an owner, provision keys or open an execution gate.

Quick check without broker requests:

    .venv/bin/python hilega-group2-readiness-v1/manage.py --repo "$PWD"

Read actual broker account/cash evidence using the existing reference-service pin and token:

    .venv/bin/python hilega-group2-readiness-v1/manage.py --repo "$PWD" --broker-read

--broker-read is explicit. It uses only the manifest-pinned installed GET-only Client: profile, funds V3, orders, trades and positions. Profile identity is checked against the existing account pin before and after, signed account evidence is verified and the complete sweep must finish in the same session within thirty seconds. The adapter's local LIVE_CLOSED scope must match the pin. Captured credentials are never printed or persisted by this package. Tokens are read only from the existing owner-private reference-service env file, not substituted from ambient shell variables. There is no login, token rotation, retry-on-permission-failure or pin enrollment.

Signed normalized financial evidence and cash previews are saved only under a fresh 0700 audit/private directory in 0600 files. Raw profile identity and tokens are not exported. Console summaries include capability checks and counts, not account IDs, tokens or cash balances. Profile/order capabilities do not prove a token has exclusively read-only scopes. Capture success does not certify strategy ownership or order permission. Funds may change during a sweep; captures are not cross-endpoint atomic.

Conservative draft candidates are tested for unknown-outcome no-resubmission, partial/cancelled residual review, half-cash preview without broker addbacks, and charge component arithmetic. They remain unapproved policies. The fee validator accepts operator-supplied aggregate numbers; it does not call the charge API, establish per-cycle attribution or mark fees complete. Actual broker cash-release/settlement handling is not implemented.

MILESTONES.json reports all six Group 2 task statuses. Group 2 remains incomplete even when all GETs succeed: trusted authority, positive execution integration, policy approvals, attributed fees and broker cash handling remain required. Existing candidate local keys are not asserted to be trusted production authority. Groups 1 and 3 do not gain additional certification from this package.

Prior 314-case closed-release regression is not rerun. Twelve new tests use fake GET/API responses and no real credentials or networks. Behavioral tests are VM-only; packaging-workspace verification is syntax/ZIP checks only. Official endpoint references and reviewed client SHA256 values are recorded in API-CONTRACTS.json.

Each new audit folder includes a local ignore-all .gitignore so financial evidence is not picked up by a normal git add. This does not change the repository-wide ignore file. Do not force-add private evidence.
