# Upstox-specific mapping, mutations disabled in code

No install/apply or running application changes. Package contains:
- mapping.py: V3 place/cancel request drafts and acknowledgement parsers,
  structural known-order matching, and unconditionally disabled mutation methods.
- demo.py/test_mapping.py: offline Upstox-shaped synthetic fixture validation.
- read.py: optional real pinned-account GET-only capture via installed adapter.

Only Python AST syntax was checked in preparation; tests/demo/API requests were
NOT run locally. VM first:
cd ~/RB-ITOS-AI
set +e
.venv/bin/python -m pytest -q hilega-production-upstox-adapter-disabled/test_mapping.py
.venv/bin/python -u hilega-production-upstox-adapter-disabled/demo.py \
 --output data/research/hilega-upstox-disabled-mapping-demo-v1

After tests/demo pass, optional read-only actual account check (no existing trade
required; no new trade should be placed just for this):
PYTHONPATH=backend:. .venv/bin/python hilega-production-upstox-adapter-disabled/read.py \
 --env-file .env --output data/research/hilega-upstox-disabled-read-v1

Existing private account pin is reused, profile checked before/after sweep,
signed adapter snapshot verified for identity/freshness, normalized orders/trades/
positions saved privately. No actual order request or active simulator update.
Credentials read locally; shell/.env token conflicts block. Output directories700,
private account samples/reports600. Terminal prints counts/status, not raw IDs.

Optional --draft PATH --known-order-id ID compares an explicitly supplied draft
and known broker ID to read-only captured fields. It NEVER discovers/adopts IDs
by tag, claims strategy ownership, binds a durable live intent, or sends an exit.
Use real local drafts only, never offline demo draft with a real account. There
are no application-issued live drafts yet. Default check is capture only.

## Verified API mapping scope
Official documents reviewed25October2026:
https://upstox.com/developer/api-documentation/v3/place-order/
https://upstox.com/developer/api-documentation/v3/cancel-order/
https://upstox.com/developer/api-documentation/get-order-book/
https://upstox.com/developer/api-documentation/get-order-details/

Documented V3 mutation host api-hft.upstox.com; request draft only. No HTTP
transport exists for POST/DELETE. read.py's installed Client is fixed GET-only.
No environment variable can turn DisabledMutations.submit/cancel/modify on.

Draft defaults: NIFTY option metadata, intraday I, DAY, integer lot quantity,
freeze/minimum checks, slice false. MARKET uses market_protection -1; custom1–25
supported in draft,0 rejected. LIMIT requires explicit normalized tick in RUPEES
and aligned limit price. Raw instrument tick-size unit conversion is intentionally
NOT guessed. Market-vs-limit policy and real normalized tick metadata still need
production approval. Drafts are not valid quote/market/risk clearance.

is_amo false is included in draft but is NOT a market-hours guard: current docs
say provider can infer AMO automatically. Future submission gate must verify
market session itself. This package never submits inside or outside market hours.

V3 placement success data.order_ids is an array. Exactly one ID acknowledges a
single unsliced draft; multiple/empty/malformed IDs require review, no blind
resubmission. ACK means accepted/reference ID, not exchange fill. Cancel success
ID acknowledges request only; readback order/fill/position proof is still needed.
Provider error classification is deliberately conservative (unknown/review, not
permission to retry). Full status/error mapping for real transport remains pending.

Read-only match requires fresh pinned snapshot, exact known order ID and matching
instrument/product/side/quantity; execution quantities must match filled quantity.
Missing order remains acceptance-unresolved, not rejected/flat. Tag is only a local
correlation hint; it is NOT server-side idempotency. Matching request fields alone
is not durable intent ownership. Cancelled order with partial fills is never
labelled flat. All match outputs ownership_verified=false/entry_permission=false.

The pure match function assumes caller cryptographically verified account capture;
read.py explicitly calls installed verify before invoking it. Boolean fixture
flags in offline tests are NOT substitutes for that verifier in a real caller.
No fake monotonic provider generation is introduced into real capture data.

## Still pending
No real mutation HTTP implementation, activation switch, live durable intent bind,
real cash reservation mapping, real risk/health/control integration, automatic
external exit attribution or production pilot. Earlier fake transport durability
checks do not become live guarantees merely because wire fields now map.
No strategy/entry/exit rule change. No additional positions opened for testing.
Production workspace stays PAUSED, reader disabled, production execution false.
This is a concrete provider-specific mapping/read layer, not deployment readiness.
