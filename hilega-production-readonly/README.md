# Production read-only validation — first stage

This standalone directory does not install or import any strategy, executor or service. No strategy rules, UI files, broker orders, credentials or settings are changed. No installer or restart is required. Do not substitute this for production execution validation.

## VM commands

Extract this directory into `~/RB-ITOS-AI`, then:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-readonly/test_readonly.py

.venv/bin/python hilega-production-readonly/run.py \
  --env-file .env \
  --samples 6 --interval 10 \
  --output data/research/hilega-production-readonly

cat data/research/hilega-production-readonly/latest.json
```

`--env-file .env` is optional: use your existing credential file path, or omit when `UPSTOX_ACCESS_TOKEN` is already exported. The CLI never requests a token as a command-line argument and never prints it. No need to send credentials here. dotenv requires the project's existing python-dotenv dependency. An HTTP 401/403 needs local credential renewal; the tool does not renew or modify credentials.

A six-sample run takes approximately a minute plus bounded request time. For a longer observation run, use tmux, `--samples 360 --interval 10`, and redirect stdout to a local log. Each request has an 8-second timeout; there are four sequential requests per sample. Interval is the pause after completing each sample, not an exact polling cadence. Ctrl+C stops observation without changing orders or services. Each invocation starts a new baseline.

## What the report proves

| Field | Meaning |
|---|---|
| connection_status PASS | Profile, order book, daily trades and positions returned structurally valid successful responses in that sample |
| LIVE_READ_ONLY | Evidence came from the production GET APIs |
| OFFLINE_FIXTURE | Test data only; never live evidence |
| BROKER_POSITION_REDUCED | Same account instrument/product has a smaller nonzero position |
| BROKER_POSITION_NOW_FLAT | Same instrument/product explicitly reports zero after a previous nonzero sample |
| POSITION_ROW_APPEARED_OR_MISSING | Row presence changed; absence is not accepted as a confirmed exit |
| NOT_CLEARED_FOR_PRODUCTION | Execution readiness is deliberately blocked regardless of connection success |

Only allowlisted fields are saved. Profile personal fields, raw error bodies, tokens and account identifiers are excluded. Order/trade IDs and contract/position details remain sensitive: keep reports local and review before sharing. New output files have restrictive permissions. Existing directory/file permissions are not repaired by this tool.

Snapshots are sequential, not atomic across endpoints. An order and a position can temporarily disagree during fills. Polling can miss changes that open and close between samples. Position changes are account-level evidence, not proof of which app/user initiated them. Manual or automatic activity on the same contract cannot be attributed safely from net quantity alone. No report changes the application's strategy state or historical decision audit.

## Still required before production

1. Explicit strategy-owned order-ID ledger, with instrument/product and actual filled quantities. Never identify ownership from instrument alone.
2. Portfolio order/position stream plus periodic REST reconciliation; reconcile after restart and reconnect before new entries.
3. Connect UI manual exit and externally observed exits to the execution ledger; resolve partial fills, cancel races, unknown POST outcomes and duplicate events.
4. Serialize reversal BUY only after actual old-position closure; keep strategy events separate from broker execution events.
5. Agree contract scope (one ranked option or five), lots, allocation, trade/day loss limits, protection, operator fallback and kill-switch behavior.
6. Run offline fault tests and sandbox tests; a separate explicitly authorized small production pilot is needed for real fill behavior.

The included tests are for the VM. They were not run locally, following your preference. This package is evidence collection only, not a complete production trading adapter.

## Official endpoint references

- https://upstox.com/developer/api-documentation/get-profile/
- https://upstox.com/developer/api-documentation/get-order-book/
- https://upstox.com/developer/api-documentation/get-trades/
- https://upstox.com/developer/api-documentation/get-positions/
- https://upstox.com/developer/api-documentation/get-portfolio-stream-feed/

Offline mode accepts a JSON object with keys `profile`, `orders`, `trades`, `positions`, each containing the corresponding `{ "status": "success", "data": ... }` envelope, using `--fixture path.json`. It does not contact Upstox. It is not a simulated fill engine.
