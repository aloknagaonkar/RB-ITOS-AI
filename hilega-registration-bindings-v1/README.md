# External registration attachment and trust-binding preparation

This candidate replaces the earlier CLI test's registration-reader substitution with a real, pinned external attachment interface. It prepares a release/policy-bound trust review request; it **does not provision a production root, enable the installed factory, enroll the live database or send broker requests**.

## Run the combined VM check

```bash
cd ~/RB-ITOS-AI
unzip hilega-registration-bindings-v1.zip
.venv/bin/python hilega-registration-bindings-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-d_l5gg3t/PLAN.json" \
  --current-plan-sha256 86e185662e51e325abae7a24e06ea074f1a01afa0476e135c1fe19a5504dceac \
  --cli-review "$PWD/hilega-factory-cli-review-5exzs4z6"
```

Needs the existing venv with pytest, user systemd, unchanged earlier packages and the passed CLI review. The current installed status is checked through bootstrap-deploy v1 before and after. No package installation or application service control is performed; only a disposable rehearsal unit runs.

## Candidate interface

The immutable release retains its disabled `FACTORY-REGISTRATION.json`. When both `HILEGA_FACTORY_ATTACHMENT_FILE` and `HILEGA_FACTORY_ATTACHMENT_SHA256` are absent, default dispatch is unchanged. These settings are **not added to live environment/configuration by this package**.

An explicitly configured attachment path selects a local candidate interface:

1. Native startup pause and the real hard gate precede any private descriptor, registration, root, context or token read. The gate remains unconditionally closed in installed source.
2. After clearance (only a child-process test override here), a private file is read using its exact hash. Its schema, actual release manifest hash, policy hash, application/journal paths, current lease and expiry are verified. Descriptor lifetime is at most one hour.
3. Its pinned external registration is parsed by the original registration reader. The expected binding must match the descriptor's release, policy, lease and binding hash.
4. The existing registered worker/private loader/factory verifies the signed grant, independently pinned issuer key, private context and signed owner on every poll.
5. Attachment pointer changes, removal after admission, source changes and expiry pause and reject. A new process/lease requires explicit review and rebinding. There is no implicit fallback from an attached session, no live automatic migration and no key rotation.

Because the descriptor/grant are outside the release, they can bind to the final sealed release hash without a manifest/grant hash cycle. The external pointer/hash must eventually be bound by a separately reviewed supervisor/wrapper/recovery plan. This package does not create that live activation authority.

## One 38-case VM batch

- 6 attachment contract cases: real-gate private-read precedence, wrong release, cached expiry, changed pointer, removed pointer and wrong lease.
- 2 full outer CLI cases: native startup, fresh synthetic preparation and durable handoff, signed local bootstrap, actual attachment-file dispatch, two intercepted cycles, new-process stale attachment rejection, and cached root-change rejection.
- 30 existing registered factory/Bridge/file/lease/seed cases reexecuted against the new candidate.

The full CLI no longer patches the registration reader or file location. It still uses explicit synthetic clocks, evidence/fills, loop cadence, and intercepted transport, with a process-local order-gate override after signed disabled bootstrap. Normal registration parsing, descriptor parsing, hash checks, trust checks, dispatch and native finish/pause run. Socket hooks and the systemd Unix-only address-family restriction deny real network access. The parent gate and runtime port bytes remain closed/unchanged.

## Results and what remains

Creates a private `hilega-registration-bindings-review-*` directory containing candidate, `TESTS.xml`, `MANAGED-PROCESS.json`, before/after status, `RESULT.json`, `MILESTONES.md` and a hashed `TRUST-BINDINGS-REQUEST.json`. Success requires all 38 cases without errors, failures or skips.

The request binds the candidate release, existing one-position policy and active plan/database paths. Real account scope, issuer ID/key hash, context/owner hashes, seed, lease and final attachment hash remain **null/pending**. They cannot be honestly approved before real independent trust and fresh disabled preparation exist. Premium and daily-loss caps stay unconfigured.

Remaining live work is explicit: reviewed deployment/activation and recovery bindings; real issuer/private-file provisioning; broker timestamp semantics and actual fees/ownership evidence; fresh real disabled seed/durable handoff/enrollment; final operational qualification and controlled activation. Existing broker evidence is not recaptured or silently marked resolved.

No behavior tests ran on the development host. Static syntax/AST, dispatch anchors, pinned dependencies and ZIP integrity are the local checks; VM results decide qualification.
