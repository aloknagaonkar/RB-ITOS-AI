# Disabled dispatch request outbox

Standalone package. No apply/install, services, credentials or broker requests.
This creates an immutable broker-shaped draft outbox and an unconditional refusal
at the dispatch boundary. It is NOT a production HTTP transport or a replacement
for the installed Service. There is no environment flag that enables it.

It persists request, signal reference, policy/version and body fingerprint in a
private SQLite DB. Reusing a request ID with changed content is rejected;
repeating the same draft is idempotent. A restart retains the disabled request.
Submission/cancellation/modification and caller-imported live acknowledgements are
not implemented. A disabled attempt is recorded as BLOCKED_TRANSPORT_DISABLED,
not UNKNOWN acceptance, because no network transport exists.

A prepared SELL draft can reference a BUY draft, but that is not proof of fills,
position ownership or permission to sell. No cash is reserved or released here.
This preserves clear authority boundaries: actual verified reservation and real
acknowledgement provenance still need integrated implementation.

## VM commands

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-disabled-dispatch/test_dispatch.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-disabled-dispatch/demo.py \
  --output data/research/hilega-disabled-dispatch-demo-v1
result=$?
echo "Demo exit code: $result"
```

Use a fresh output directory. No real read/API command is needed for this step.
Only Python AST parsing was done during authoring; VM tests/demo are pending.
This package intentionally accepts broker-request drafts only; it does not accept
auth headers/tokens, resolve actual contracts or establish quote/cash eligibility.
No .env is read. Fake metadata in demo is clearly synthetic.

## Docs checked

- https://upstox.com/developer/api-documentation/v3/place-order/
- https://upstox.com/developer/api-documentation/v3/cancel-order/
- https://upstox.com/developer/api-documentation/get-positions/

See PRODUCTION_CHECKLIST.md for completed evidence, remaining steps, the proposed
pre-market schedule and required monitoring. That plan is not an installed alert
service. Production remains disabled after this package passes.
