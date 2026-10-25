# Verified account identity + read-only broker adapter

Production order submission stays disabled. This package adds three files and
changes no existing strategy, simulator, observer, UI or broker execution files.
There is no production order transport. No frontend build or service restart is
required. Existing production workspace remains PAUSED.

## Account pin

The existing broker observer deliberately removes profile identity. It must not
be used to assert which account owns an order. This new CLI verifies the actual
Upstox user_id against an ID entered privately by the operator on the VM.

Enrollment reads the profile, requests the expected ID through a hidden terminal
prompt, and rechecks the profile before saving. It never automatically accepts a
new account on first sight, and refuses to replace an existing pin. It verifies
broker=UPSTOX and is_active=true. Raw user ID, email, name and tokens are neither
saved nor printed by this CLI.

The pin contains a random local HMAC key and an opaque account scope. It lives
outside Git by default at ~/hilega-private/upstox-account-pin.json, mode 600 in a
private directory. Symlink pin files, public/group-readable files/directories,
invalid pins and mismatched accounts are rejected. Keep this file private and
securely backed up; do not include it in source ZIPs or chat. Its key binds
snapshot integrity and account scope across token renewals. Losing/replacing the
pin requires explicit recovery; there is no automatic repinning feature.

This is local verification of broker account identity, not production trading
authorization or proof that an order belongs to the strategy.

## Adapter behavior

- Existing fixed-URL GET-only Client, with application User-Agent and redirects
  disabled. No POST/PUT/DELETE or order/strategy control imports.
- Sequence: profile -> order book -> today's individual trades -> positions ->
  profile. The same immutable client/token is used throughout the sweep.
- Both profile checks must match the pin. Profile or endpoint failure stops the
  sweep; the CLI makes no automatic retries and never persists provider text.
- Source data is sanitized into instrument/product/side/quantity/status/order ID,
  trade ID, fill price and timestamps. Unneeded profile/order fields are dropped.
- Official active and terminal order statuses are explicit. Unknown statuses
  require review. Cancel pending/not cancelled remain active; they are not exits.
- Order quantities and individual trade quantities remain separate. Missing
  executions are never manufactured from an order's status or average price.
- Identical trade duplicates are deduplicated; conflicting duplicates and
  mismatched instrument/product/side are blocked. Invalid/nonfinite/zero fill
  prices, missing timestamps, future trades and wrong-day data are rejected.
- The documented naive exchange-local timestamp examples are interpreted as IST;
  explicit offsets are honored. This timezone interpretation still needs checking
  against actual populated account records. Date-only values are not trade times.
- Captures are sequential and NOT atomic. Mismatched order/fill totals are marked
  REVIEW_REQUIRED because lists can change during a sweep.
- A live strategy ownership map does not exist yet. Every broker order is reported
  unmapped and nonzero exposure is flagged for review. No symbol/tag-based adoption.
- Empty lists are labelled EMPTY_ACCOUNT_SNAPSHOT_ONLY, not proof of live strategy
  exits, fills or production readiness. Missing evidence is unknown, not zero.
- Capture must finish within 30 seconds without crossing IST midnight. The local
  verifier also requires a fresh, matching-account, correctly signed live snapshot.
- JSON output contains an HMAC signature, never the HMAC key. Modifications,
  fixture-mode relabeling, unexpected execution flags and stale evidence fail
  verification. This protects local integrity under the private-file model; it is
  not hardware-backed attestation or protection against a compromised VM user.
- A blocked capture writes a new signed BLOCKED report without position/order/fill
  arrays rather than retaining an earlier successful snapshot as current.
- No realised/unrealised P&L is claimed. No live ownership database is written.
  The earlier fixture ledger still rejects this LIVE_READ_ONLY_ACCOUNT_PINNED
  format. Do NOT relabel a live snapshot as OFFLINE_FIXTURE to feed that ledger.

## Stage and validate on the VM

Upload/extract in ~/RB-ITOS-AI. Do not copy source files manually into backend.

```bash
cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-account-adapter.zip
.venv/bin/python hilega-production-account-adapter/install.py \
  --stage data/research/hilega-account-adapter-stage
.venv/bin/python hilega-production-account-adapter/validate.py \
  --stage data/research/hilega-account-adapter-stage \
  --output data/research/hilega-account-adapter-validation.json
```

Validation is offline: all network operations in new tests are forbidden or
explicitly stubbed. It includes existing control, ownership, observation and
strategy/dispatch regression tests. No tests, capture, replay or build were run
in the preparation environment; only Python AST syntax checks were run.
There are no frontend changes, so frontend build is not part of this milestone.

Installer additionally checks exact hashes of the previously validated funds-
fixed broker observer and fixture ownership ledger. If those differ, it stops
without replacement. Do not bypass the guard; supply the changed source for review.

After validation PASS:

```bash
.venv/bin/python hilega-production-account-adapter/install.py --apply \
  --validation data/research/hilega-account-adapter-validation.json
```

After APPLIED, enroll ONCE from an interactive SSH terminal:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_account_adapter.py enroll
```

It prompts for your Upstox User ID (the broker account identifier, NOT your API
access token, API key, mobile number or workspace control key). Obtain that ID
privately from your Upstox account. Input is hidden. Do not paste it into chat.
The token is read locally from HILEGA_PRODUCTION_BROKER_READ_TOKEN if configured,
otherwise UPSTOX_ACCESS_TOKEN. Shell environment takes precedence over .env.
No existing credentials are changed or refreshed by this CLI.

After ACCOUNT_PIN_CREATED, collect and immediately verify one snapshot:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_account_adapter.py snapshot
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_account_adapter.py verify
```

Snapshot performs five GETs. Verify reads local files only and must run within
30 seconds of the sweep start. If time elapsed, an expired verify is expected;
only collect a new snapshot if there is no unresolved access/auth block.

Default snapshot: data/research/hilega-production-account-adapter/latest.json.
Keep account snapshots out of Git and shared ZIPs. Console output contains safe
statuses, counts and diagnostic codes; it does not print order rows or balances.

Optional global arguments precede the action:
--env-file PATH, --pin-file PATH, --snapshot-file PATH.
A snapshot cannot overwrite the pin file. No fixture input or production-enable
flag exists. Keep production PAUSED; pin enrollment does not arm any worker.

## Expected first validation

On an account with no current orders/trades/positions:
- ACCOUNT_PIN_CREATED on enrollment.
- READ_ONLY_CAPTURED, account_identity_verified=true, zero counts on snapshot.
- IDENTITY_AND_READ_ONLY_EVIDENCE_VERIFIED on immediate verify.
- entry_permission=false and production_execution_enabled=false throughout.

If current account activity exists, unmapped activity diagnostics are expected;
identity may be verified while strategy ownership remains unverified. Do not
place a real order just to populate this validation. An empty-day success does
not validate actual fills or external exits.

## Pending next integration

Bind real strategy-event intents to broker order IDs through the shared execution
controls; adapt fresh verified snapshots to a dedicated live ownership ledger;
validate partial/external activity and reversal serialization there. Then expose
that read-only reconciliation state in UI. The current observer/UI and its
NOT_VALIDATED readiness flags are unchanged by this package. Production transport,
risk reservation, contract checks, loss limits and controlled pilot remain pending.

## Official schema references

https://upstox.com/developer/api-documentation/get-profile/
https://upstox.com/developer/api-documentation/get-order-book/
https://upstox.com/developer/api-documentation/get-trade-history/
https://upstox.com/developer/api-documentation/get-positions/
https://upstox.com/developer/api-documentation/appendix/order-status/
