# Pinned private context and read-only provider candidate

Previous VM checkpoint: 222 combined factory/lifecycle cases passed, and the bounded post-deployment observation passed. The running application remains preparation-only, paused, with no enrolled execution candidate.

## Combined work

* A real private-file context loader with an explicit reviewed config digest, owner-only files/directories, no symlinks/hardlinks, expiry and pinned identity/token hashes.
* Existing account-pin validation and independent local-authority validation; the capture key cannot serve as execution authority.
* Read-only verification of the existing adapter metadata and signed exclusive-route owner. The loader never enrolls an owner, creates a key or adopts a seed automatically.
* Deferred GET-only account/entry captures, plus an owned-contract quote collector that avoids funds or current ATM selection.
* Connection to the verified execution-session factory, with temporary private files and intercepted transport in tests.

## VM command

```bash
.venv/bin/python hilega-private-context-v1/apply_and_test.py --repo "$PWD"
```

Expected: bounded closed-deployment checkpoint PASS and 14 targeted cases. Optional combined candidate integration, expected 236 overlapping cases:

```bash
.venv/bin/python hilega-private-context-v1/apply_and_test.py --repo "$PWD" --integration
```

Keep all prior corrected packages, successful 222-case factory report, original approved rollout plan, compatibility review, and the factory's verified stage. The loader, credential files, authority and enrollment used by the positive tests are synthetic/temporary. The runner creates no real private context or authority files and does not enroll the live database. No local behavioral tests were run; syntax checks only.

## Context contract

PrivateContextLoader receives the exact existing Source/adapter Store/journal plus a private config path and externally supplied expected config SHA256. It does not construct a Store or mutate database schemas. The installed order gate runs before any private reads, even when the loader is invoked directly. The factory also checks that gate before invoking its loader. Environment variables cannot activate this path.

The exact config fields are model, production_execution_enabled, application_db, adapter_db, journal, seed_request_id, bridge_run_id, pin_file, pin_sha256, authority_file, authority_sha256, broker_token_file, broker_token_sha256, issued_at and expires_at. Model is HILEGA_PINNED_PRIVATE_CANDIDATE_CONTEXT_V1; production_execution_enabled must be false. Paths are explicit and bound to existing Source/store/journal and lease. Validity is at most one day. No template containing real secrets is generated.

The authority file is the existing exact account_scope/authority_id/key structure, with a separate key from the account-capture pin. Pinning a local file is not provisioning externally trusted production authority. That remains an operator-approved future step. No authority grant or execution permission is issued here.

Broker token contents remain deferred until a provider capture or transport send requests them. The pinned token file must not rotate silently; rotation requires a newly reviewed context. Every fresh capture rechecks config/identity hashes and expiry. Expired contexts fail closed; cached-session recovery can avoid fresh capture, but a fresh process with an expired config requires a separate reviewed recovery/config path. This is a documented availability limitation, not permission to bypass expiry.

The owned quote collector checks profile before/after and the exact held contract, gathers only market/contracts/exact quote, signs evidence and runs the existing quote/grid validator. Full signed account captures are retained; rows are never removed or re-signed to manufacture ownership. Current ATM and funds checks remain part of entry capture, not owned-quote collection. Policy/fee/tick approvals remain pending.

## Deployment boundary

The existing adapter Store is explicitly injected by the caller. A production bootstrap/provider registration and credential provisioning workflow is not installed. The current worker is unchanged and no live context loader is configured. The tests intercept the immutable installed gate and order transport only inside pytest. Real broker network validation, signed production authority provisioning, initial route enrollment, full dependency/release reconciliation, fees/cash handling and full release regression remain pending. Production execution/readiness stay false.
