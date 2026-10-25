# Read-only real cash/order observation

No installation/apply, services, simulator DB access, orders, deposits or trades
required. Fixed existing Upstox Client GET routes only: profile, V3funds, orders,
trades and positions. Reuses existing private account pin; verifies profile before
and after every sweep. .env read locally; conflicting shell/.env token values
block. No raw token/account ID/profile/error body is printed or saved.

Run unit tests first on your VM. Only AST syntax was checked in preparation;
no tests, live API requests, demo or frontend build were run locally.

cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega-production-cash-observation/test_analysis.py
PYTHONPATH=backend:. .venv/bin/python -u hilega-production-cash-observation/run.py \
 --env-file .env --samples 3 --interval 10 \
 --output data/research/hilega-real-cash-observation-v1

New output path required. Existing pin default:
~/hilega-private/upstox-account-pin.json (override --pin-file if needed).
Token HILEGA_PRODUCTION_BROKER_READ_TOKEN, otherwise UPSTOX_ACCESS_TOKEN.
Three samples normally require20seconds plus API time. Progress prints each sample.
Every GET timeout8s; sweep >30s or session rollover blocks its evidence. Each
snapshot retains its own start/end; separate endpoint responses are not atomic.
Funds are read before and after order/trade/position retrieval, not assumed stable.

Output sample-001.json etc, report.json and summary.md. Snapshots and report are
signed with existing private pin's HMAC key, which is never persisted here. Signatures
are for evidence integrity, not trading permission. Raw order/trade IDs and public
instrument IDs remain in private samples for subsequent manual linkage. Cash values,
positions and IDs are sensitive: directory700/files600. Do not upload raw reports
publicly or commit to Git. CLI table shows deltas/status, not account identity.

Captures:
- Net cash_available_to_trade.total; margin_used.total.
- Optional premium_present/span_exposure/MTF and cash-activity components.
- Profile-verified normalized orders, trades and positions through existing adapter.
- Comparison: cash/margin/premium changes, new/changed orders/fills, missing or
  corrected evidence, positions and deposits/withdrawals/stock-sale-credit changes.

No debit attribution is inferred. Even a fill and equal cash drop can coincide
with charges, other activity or non-atomic endpoint publication. A pending order
may already affect broker cash; never automatically subtract its premium AGAIN,
add margin back, or import simulator reservations as real cash adjustments.

Account-wide data does not establish strategy ownership. Existing adapter
mismatch/unmapped diagnostics are retained. READ_ONLY_CAPTURE_PASS means captures
completed, NOT that ownership/cash mapping/risk controls passed. Every report
has debit_attribution=NOT_VALIDATED, entry_permission=false, production_ready=false.
Empty account Sunday evidence can validate connectivity/schema only. No observed
activity is NOT proof of order-reservation accounting. No trade should be placed
just to make this report show activity.

Current collector does not read or modify local allocation ledger. Real broker
cash/local hold matching and safe acknowledgement transitions are still pending.
No automatic orders, releases, real-funds enrollment or production activation.
Any live matching must rely on verified own order/fill evidence and a coherent
funds snapshot, including concurrent external account activity and release timing.

Exit0=all sample captures succeeded. Exit2=one/more sample captures incomplete
or setup blocked. Comparison regression flags can still appear with successful
captures; review the report rather than treating exit0 as reconciliation approval.
The collector never retries a mutation: no mutation endpoint is present.

Official funds semantics reviewed25October2026:
https://upstox.com/developer/api-documentation/get-funds-and-margin-v3/
Net cash available is net cash; margin_used/premium are separate observations.
No reconstructed gross cash formula is approved by this package.
