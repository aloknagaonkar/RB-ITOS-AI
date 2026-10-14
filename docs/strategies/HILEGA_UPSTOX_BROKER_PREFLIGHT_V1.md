# Hilega Upstox Broker Preflight V1

## Objective

Validate broker plumbing before any live order is permitted. This phase does
not change Hilega V1, WMA-gap V2, canonical exits, paper controls or quantity.

## Three isolated lanes

| Lane | Credential | Commands | Money risk |
|---|---|---|---|
| Live market/account read | `UPSTOX_ACCESS_TOKEN` | Profile and market data only | None |
| Internal paper | Existing SQL paper ledger | Simulated ASK entry / BID exit | None |
| Upstox Sandbox mirror | `UPSTOX_SANDBOX_ACCESS_TOKEN` | Place, modify, cancel | None |

The implementation contains no live order method or live order URL.

## Preflight

Print the audited capability manifest:

```bash
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_broker_preflight_v1
```

Check the live account read-only profile:

```bash
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_broker_preflight_v1 --profile
```

Required PASS checks are active account, NFO enabled, I or D product, and LIMIT
orders available.

## Sandbox command roundtrip

Use an exact current option instrument, valid lot quantity and harmless sandbox
limit price. The command places, modifies and immediately cancels a Sandbox
order. It never uses the live order host.

```bash
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_broker_preflight_v1 \
  --sandbox-roundtrip --confirm SANDBOX_ONLY \
  --trade-id HILEGA-PREFLIGHT-001 --session-date YYYY-MM-DD \
  --direction BULLISH --instrument-token 'NSE_FO|...' \
  --quantity LOT_SIZE --price LIMIT_PRICE --product I
```

For a bearish Hilega signal, use `--direction BEARISH`; the validator requires
a PE intent. Bullish requires CE. Both are option buys; exits are not tested by
this cancel-only preflight.

## Acceptance checklist

- [ ] Capability manifest says live order endpoint absent.
- [ ] Live profile read passes active/NFO/product/LIMIT checks.
- [ ] Sandbox token is separate from live token.
- [ ] Bullish maps to CE BUY and bearish maps to PE BUY.
- [ ] Instrument key, lot quantity, limit price and product are explicit.
- [ ] Place returns an order ID.
- [ ] Modify uses that exact order ID.
- [ ] Cancel uses that exact order ID.
- [ ] Provider errors are stored without tokens or complete response bodies.
- [ ] No Sandbox result is labelled as a real exchange fill.
- [ ] Internal paper and Sandbox records share the strategy trade ID.
- [ ] Live execution remains disabled.

## What this phase does not prove

Sandbox command success does not prove real exchange fills, fill latency,
portfolio-stream delivery, broker positions, charges or production
reconciliation. Those require later isolated certification gates.
