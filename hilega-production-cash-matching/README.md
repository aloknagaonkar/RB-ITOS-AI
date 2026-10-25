# Offline broker-cash / local-reservation evidence model

NO installer/apply, service restart, credentials, network, actual order, simulator
DB access or ledger updates. Tests/demo only use synthetic fixtures. Live account
collector records are deliberately REJECTED as inputs; polling cash changes do
not provide the explicit per-order attribution assertion required by this model.

VM commands:
cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-cash-matching.zip
.venv/bin/python -m pytest -q hilega-production-cash-matching/test_matcher.py

After tests pass:
.venv/bin/python -u hilega-production-cash-matching/demo.py \
 --output data/research/hilega-cash-matching-demo-v1

Only Python AST syntax was checked in preparation. Tests/demo were NOT run locally.
No market session or real trade is needed. Output is summary.md/report.json under
NEW directory, containing only synthetic data. No installed source is changed.

## Proposed evidence contract, not production policy approval
Snapshot must declare OFFLINE_FIXTURE, matching account/snapshot identifiers,
complete/coherent evidence, same IST day, <=30seconds old, explicit cash-activity
classification, unique broker order identities and position rows. Sequential live
GET sweeps are non-atomic and cannot be relabelled coherent to satisfy this gate.

Each local reservation has an explicit bound order, instrument, product, quantity
and estimate. A reflected_amount is an EXPLICIT_OFFLINE_ATTRIBUTION_ASSERTION;
it is NOT an Upstox API field and the model does NOT infer it from equal cash/fill
changes. This is a deliberately trusted test fixture input. Validating the source
of such evidence in real trading remains unsolved/pending; no boolean or amount
from an untrusted client is sufficient proof.

The preview arithmetic for each valid reservation:
full local hold remains until terminal-flat evidence;
unreflected local deduction = max(0, full hold - explicit reflected overlap).
Capacity preview = max(0, floor(50% current broker net cash) - sum(unreflected)).
No broker margin/premium is added back to cash. Reflection never itself releases
the underlying hold. Fees/slippage buffer not reflected remains deducted.

Example fixture: reservation6600 = premium6500 + buffer100. Broker net cash93500;
explicit order-linked reflection6500 means hold6600 retained but only100 additional
unreflected deduction. Current half-cash cap46750; capacity preview46650. This is
synthetic arithmetic, not a recommendation or actual broker balance.

UNKNOWN acceptance, missing/wrong-scope proof, missing order, quantity/identity
mismatch or excessive reflection retains full hold and marks review. Unmapped
orders/positions or unrelated/unknown cash activity invalidates reflection and
release suggestions for the account. Stale/noncoherent input raises Blocked.
Missing input is never zero evidence. Duplicate reservation/proof/order mappings
and a broker order reused across reservations are rejected.

Cancellation pending, entry filled and exit pending never release funds. Even a
cancelled entry can have filled exposure. TERMINAL_FLAT additionally needs explicit
position0 plus aggregate all-related-orders-terminal and exit-fills-verified
fixture assertions. These flags stand in for future verified ownership evidence;
they do NOT implement real fill reconciliation. Release is an output suggestion
in synthetic analysis only; no durable ledger is modified.

Function is pure/deterministic, no snapshot history store or durable transitions.
The earlier ledgers cover persistence separately. Stale ID reuse across different
invocations needs a future authenticated/versioned integration layer. Complete
coherent snapshot flags are input assertions, not proof that a real source is
complete. All output retains entry_permission=false, production_execution_enabled=
false and real_debit_attribution=NOT_VALIDATED.

MATCHED_OFFLINE_FIXTURE means only supplied synthetic assertions were internally
consistent with this model. It is NOT cash reconciliation clearance or production
entry approval. A false new_entry_eligibility_blocked flag only means this offline
cash-evidence check did not request review; quote, Pause, position/exposure,
capital availability, daily loss and order submission gates still apply.

Open risk/implementation questions before real integration:
- Provider-verifiable per-order debit/reflection evidence and freshness sequencing.
- Account-wide concurrent orders, deposits, withdrawals, charges and cash drift.
- Whether50% applies to current net cash per trade or a fixed session budget;
  this preview uses current net cash and is not a total-session exposure limiter.
- Real exposure/ownership checks, partial basket attribution, reservation lifecycle
  and guarded release. Production currently supports no live allocation mapping.
- Signed/verified collector ingestion cannot turn correlation into attribution.

Do not change the running central simulator's conservative cash logic based solely
on this demo. No addback/reflection optimization is deployed. Production workspace
stays PAUSED/unfunded and execution disabled.
