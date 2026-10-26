# Signed evidence input for preparation — closed-gate preflight

Standalone GET-only collection + read-only preparation preview. Adds only this
new package. No application installer/apply, API/worker restart, strategy changes,
UI changes, order transport, broker mutations, arming, intent insertion,
reservation creation/release or production enablement.

## Why this stage exists

The previous preparation milestone passed 41 VM tests, all seven demo checks and
65 installed control/health regressions. That stage accepts explicit synthetic
funds/quotes only. The real closed adapter has zero requests/attempts/receipts.
Neither milestone proves real contracts, quotes, cash reservation or ownership.

The older contract preview is unsigned. This package collects selected raw
contract/quote inputs using its existing fixed GET-only MarketClient, reuses the
existing signed cash collector, verifies the account pin before and after the
combined sweep and signs the complete evidence bundle with the local pin key.
An unsigned old report or a synthetic stage-mode record is not a live input.

A local signature protects persisted content under the pin; it is NOT a broker
signature or independently authenticated transport receipt. Someone able to alter
local code/data and obtain the private key can forge local records. Source files,
credentials and output directories must remain private and trusted.

## Data flow

Pinned profile -> cash before market sweep -> market state + underlying + broker
contract metadata + selected quotes -> signed account/cash sweep -> market state
+ cash after market sweep -> pinned profile -> signed combined bundle.

The independently verified preparation preview reselects ATM from the recorded
nearest-expiry strike grid and final underlying quote. It requires one CE and one
PE as separate directional alternatives; it never buys both. Lot/minimum/freeze
come from returned metadata, not a hardcoded lot size. No fallback guessed key.
Only exact NSE_FO|numeric option keys are accepted by the new validator.

Provisional preview checks reuse existing rules: NORMAL_OPEN at sweep start/end,
combined sweep and conservative start-based freshness <=30s, quotes <=10s,
last option trade <=60s, positive two-sided depth, no crossed book, spread <=2%
of midpoint, bid/ask best depth covering one lot, positive volume, unchanged ATM,
pinned account scope, unchanged cash across the whole sweep and no unowned account
activity/positions/diagnostic issues. Proposed cost is observed ask * one lot +
INR100 provisional buffer, compared with 50% observed net cash.

These are draft preview thresholds, not approved production risk settings.
Sequential API reads are NOT an atomic remote snapshot and cannot rule out activity
that occurs and reverses between reads. No broker debit reflection or fees are
attributed; no cash is added back. Other shadow books are NOT aggregated, and this
preview never claims remaining spendable allocation or global reservation capacity.

The raw metadata tick_size is retained with its provenance but is NOT assumed to
be rupees or automatically converted. The docs expose tick_size without an explicit
unit in the reviewed field description. The preflight creates NO executable LIMIT
request and sets tick_units_verified=false. A reviewed normalization/limit-price
policy is still required before wiring an actual request. The earlier synthetic
stage's explicit rupee tick is never copied into live evidence.

Each candidate retains fingerprints of the entire bundle, nested cash capture,
selected contract and selected quote. A preview is a bound data input for future
controller integration, not an installed execution intent or a reservation.
It cannot be fed into the old synthetic Preparation API by relabelling its mode.

## Ubuntu VM: tests first

Extract the ZIP in ~/RB-ITOS-AI; only hilega-production-evidence-preflight/ is added.

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-evidence-preflight/test_evidence.py
```

All test account/contract/cash/quote records and the mocked collector are synthetic,
even where a test record uses the live-format mode to exercise validation. No
network or real credentials are needed by tests. They never establish live proof.
Author checks were static review and Python AST syntax ONLY; no tests, imports,
application changes, broker reads or orders were executed locally.

## First real read: capture only, after tests pass

Use a fresh output directory. This mode needs no strategy signal, control version
or worker ID and never reads/modifies controller state:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-evidence-preflight/run.py \
  --capture-only \
  --output data/research/hilega-evidence-preflight-read-v1
```

Existing .env and ~/hilega-private/upstox-account-pin.json are used locally. The
collector checks shell/file token conflicts, prefers
HILEGA_PRODUCTION_BROKER_READ_TOKEN and otherwise UPSTOX_ACCESS_TOKEN. No new pin
enrollment, key sharing or deposit is needed. Existing pinned GET-only clients
are reused; no order endpoint or mutation transport is imported.

Run a market-hours sample to validate fresh market quotes. Outside market hours,
closed-market/stale/no-depth results are expected blockers, not software success.
If observed cash remains zero, NO_CASH_CAPACITY/HALF_CASH_CAP_EXCEEDED is expected.
Do not fund an account or alter thresholds solely to make this preview pass.

Output directory must not exist. Private evidence.json contains the signed
bundle; report.json contains the assessment and preparation previews. Files are
owner-only. Stdout omits account IDs, scope, pin/key, contracts, cash amounts,
quote details and evidence fingerprints. Share stdout and test summaries only.
No raw profiles, tokens or complete API bodies are saved. These two private JSON
files are evidence only; keep them out of public Git or uploaded code bundles.

Exit 0 in capture-only mode means READ_ONLY_EVIDENCE_CHECKS_PASS with
controller_checks_performed=false. It is NOT controller admission or readiness.
Exit 2 means NOT_CLEARED/BLOCKED. A new failed run never reads an old successful
report as its current result. Existing output is never overwritten.

## Optional controller preflight (later, with actual current signal details)

Full mode accepts --direction BULLISH|BEARISH, --expected-version INTEGER,
--bridge-run-id CURRENT_ID and --signal-at ACTUAL_AWARE_SIGNAL_TIMESTAMP instead
of --capture-only. Do not fabricate a signal or arm the application to test it.
Defaults are the confirmed workspace sim.sqlite and closed adapter adapter.sqlite
under data/research; overrides are --controller-db and --adapter-db.

It reads those source databases read-only and reports Pause, version/session,
stop generation, reconciliation age, post-Resume signal freshness, bridge health/
lease and existing controller/stage/adapter activity. It requires exact pinned
adapter scope equality and LIVE_CLOSED mode; a matching scope prefix is insufficient.
Any existing execution/hold/adapter activity is conservatively REVIEW_REQUIRED.
It separates evidence_checks_passed from control_checks_passed. Good market
inputs cannot clear Pause or stale reconciliation.

The source DBs and endpoint sweep are independent snapshots, not an atomic
control/transport transaction. These are installed SIMULATOR control/health fields;
their local checks do NOT verify real broker reconciliation. Even a full-mode
READ_ONLY_PREFLIGHT_CHECKS_PASS has production_ready=false, all execution flags
false, no executable request and controller_integration_installed=false.
No hold is reserved, released or credited, and no simulator evidence is relabelled
as real fills. Other live cash/reservation books still need production integration.

## Still pending

- Reviewed tick normalization and real executable request/price protection policy.
- Installed controller evidence-provider wiring and atomic control/reservation/
  request admission with real cash, fee, debit/reflection and risk handling.
- Daily-loss settings, production market calendar/session/feed/quote rules.
- Genuine acknowledgement provenance, actual fills/positions and scoped ownership.
- External exits, partial cancel/cleanup, manual exits and no oversell.
- Real terminal-flat proof and exactly-once release authority.
- Live P&L/UI, readiness/alerts/escalation, recovery/backup/rollback and separately
  authorized supervised pilot after all required gates pass.

Official references inspected for field/endpoint grounding (26 October 2026):
https://upstox.com/developer/api-documentation/get-option-contracts/
https://upstox.com/developer/api-documentation/instruments/
