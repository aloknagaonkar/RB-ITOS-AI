# Exact real issuer-material provisioning plan

The default command prepares a plan only. A separately hash-approved `apply` creates **one actual private issuer key** and a **disabled registry** outside the repository. This is material preparation, not production trust enablement or order authority.

## Prepare on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-issuer-provision-v1.zip
.venv/bin/python hilega-issuer-provision-v1/manage.py \
  --repo "$PWD" \
  --active-plan "$PWD/hilega-group2-upgrade-plan-qfgbdwft/PLAN.json" \
  --active-plan-sha256 4dc497c053d41c136559b3c4ef9918598ddc6bb1b3f5447fe89032a79456c7f5 \
  --evidence-review "$PWD/hilega-live-prerequisites-review-djuyjmst" \
  --requirements-sha256 c842e3268e255cb4668b673cacc880843e7d451e7c4dd6d31f2ef0f9eac8efa7
```

Requires existing venv/pytest/dotenv, earlier rollout packages, the applied plan, recent signed account evidence and the running source worker. Performs no broker requests or application service control. The default check verifies current status before/after, release/configuration hashes, signed account scope, paused/empty databases and a new private destination. It reads the existing source credential context in memory for key independence; credential values are never printed or copied to artifacts.

Ten VM-only synthetic storage checks cover disabled/private output, no overwrite, same-key interruption recovery, missing/changed key rejection, edited registry rejection, symlinks, insecure parents and capture/token-key collision. No real key is created by these tests or by plan preparation.

A pass prints `PLAN.json`, exact SHA256, real key/registry destinations and a 30-minute `apply_before`. `MILESTONES.md` is created beside the plan. The recent profile-bound signed evidence must be no older than 24 hours when preparing the plan; stale evidence requires a refresh, not a bypass.

## Real material creation after exact plan review

Use the actual path/hash printed by the check:

```text
.venv/bin/python hilega-issuer-provision-v1/manage.py --repo "$PWD" --action apply --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 PRINTED_PLAN_SHA256
.venv/bin/python hilega-issuer-provision-v1/manage.py --repo "$PWD" --action status --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 PRINTED_PLAN_SHA256
```

Apply requires the same account/release/configuration, current paused/empty state, unexpired plan and unchanged source process. It takes the shared maintenance lock, creates private parent directories as needed (0700), generates 32 cryptographically random bytes distinct from the capture key and current broker token, and creates the issuer key (0400), disabled registry (0400), durable intent and receipt (0600). The root resides below `~/hilega-private/production-issuers/<account-scope-hash>/`; neither the key nor real broker token is stored in the repository/plan folder or displayed. Only file paths and fingerprints are reported.

The registry binds account scope, deployed release, issuer identity and key hash, with `enabled: false` and `production_execution_enabled: false`. The existing trust loader will reject a disabled registry. No grant is issued and no factory pointer, wrapper, service, controller, database or live owner is changed. Key creation does not certify independent organizational approval of the issuer; that review and registry enablement remain pending.

## Interruption recovery

If a durable key was written before interruption:

```text
.venv/bin/python hilega-issuer-provision-v1/manage.py --repo "$PWD" --action recover --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 PRINTED_PLAN_SHA256
```

Recovery accepts only the approved intent, identical key fingerprint and exact disabled registry bytes. It never generates or replaces key material. An absent/partial/changed key or externally changed registry blocks recovery for review. If interruption occurred before the key became durable, this tool does not delete the directory or invent a replacement; inspect the private state before planning any fresh operation.

Expiry prevents initial key generation. Explicit recovery may finish the same disabled files after expiry, subject to unchanged account/release/configuration and paused/empty live state. A source restart is allowed for read-only status or same-key recovery; it does not rebind a lease or enroll anything. Existing keys/destinations always require review; there is no automatic rotation or delete/rollback action. Arbitrary disk/power failures are not certified by the named synthetic checkpoints.

## Remaining live gates

This package does not resolve broker timestamp semantics, final fee attribution, full contract identity or strategy ownership. It does not create a fresh real preparation or enroll a source owner. Exact activation wrapper/supervisor/recovery approval, real evidence/enrollment and final operational/gate-release readiness remain necessary. Capacity remains one; premium/daily caps remain unconfigured. Execution stays disabled.

Static syntax/AST and archive checks only were performed locally. Behavioral validation is left to the VM as requested.
