# Signed live-account evidence continuity review

This is the first read-only part of real account reconciliation. It uses the installed pinned-account GET-only adapter. It does not install into the application, change controls, send/cancel orders, bind strategy ownership, release reservations or enable production.

## What it checks

- Local signature, pinned account scope, capture freshness and same-session evidence.
- Explicit order/trade quantities and identities; no fill inference from acknowledgement or average price.
- Previously observed fills cannot disappear/change; filled quantities cannot regress.
- Previously terminal orders cannot change and previously observed orders cannot disappear.
- Between accepted captures, account position delta must match the signed sum of newly observed BUY and SELL fills for that instrument/product.
- A reduced long account position supported only by new SELL fills is reported as `ACCOUNT_LONG_REDUCED_UNATTRIBUTED`; zero remaining as `ACCOUNT_LONG_CLOSED_UNATTRIBUTED`.
- Duplicate/overlapping/out-of-order captures, stale data and inconsistent evidence require review. They never replace the last accepted baseline. The latest result, including failure, is persisted separately.
- A restart retains history. A new trading session requires a new output directory; overnight activity is never inferred to be a strategy exit.

The snapshots are sequential endpoint sweeps, not atomic broker snapshots. A fill arriving during a sweep can produce a temporary inconsistency. The result must stay REVIEW_REQUIRED until a later complete capture reconciles; no application permission is granted by this tool at any point.

## Limits that matter

A matching position delta establishes account-level arithmetic only. It does NOT establish that the SELL came from the Upstox UI, belongs to this strategy, or closed a particular strategy entry. Concurrent BUY and SELL activity is reported as unattributed account activity. An empty account validates only empty-account observations. There is no P&L or cash debit attribution. No production control or ledger reads/writes are wired.

Further work must bind live acknowledgements to durable strategy intents, reconcile individual fills against those bindings, and apply verified external-exit changes to the application. Those steps are not implemented by this package.

## VM validation (no installer/apply/restart)

From the repository root:

```bash
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-live-evidence-review/test_review.py
```

Tests use signed synthetic captures only; no broker calls. They do not prove live fills.

After tests pass, capture three real read-only samples, choosing a fresh output path for the current date:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-live-evidence-review/run.py \
  --env-file .env \
  --samples 3 \
  --interval 10 \
  --output data/research/hilega-live-evidence-review-20261026

result=$?
echo "Review exit code: $result"
```

Use the existing private account pin. Do not paste tokens, pin contents, raw profile data or private evidence files into chat. Stdout omits raw account IDs and tokens. Share only the stdout results.

Exit 0 means all supplied captures passed read-only continuity checks. Exit 2 means blocked/review required, never permission to trade. A later failure leaves the last accepted baseline intact and stores a failure as the latest review state. Existing application state and HTTP submission gate are unchanged.

The dedicated directory stores private signed raw captures in `evidence.sqlite3` and a scope marker. Do not reuse it for controller/ownership/allocation databases or across accounts. Keep it private; it is not an installable application ledger. The marker and SQLite file have mode 0600. The pin/key/token is never stored there.

Author validation: Python AST parsing only. All tests and real reads must run on the user's VM.
