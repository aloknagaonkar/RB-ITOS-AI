# Installed controller / closed broker adapter link validation

This is the integration contract and isolated validation step before an application
rollout. It reuses the installed Service/SimBroker/allocation module and the just-
validated closed broker adapter. No installer/apply, API restart, active DB, actual
journal, strategy worker, account token or broker request is used.

The link is explicitly restricted to marked isolated databases created by the
fixture builder. It refuses the normal running workspace database. The installed
Service's atomic reservation/intent path runs first; the fixture stops precisely
before SimBroker transport, then exercises the adapter boundary. It does not
replace the Service broker port or create an environment switch for production.

## What is verified

- Matching controller intent and reservation ID, instrument, quantity and held cost.
- Authoritative controller ARMED state; pending durable stop veto; fresh signal,
  reconciliation, synthetic funding and existing bridge-health checks.
- Explicit synthetic option metadata mapping, never inferred from a simulator symbol.
- Immutable adapter preparation with the controller reservation reference.
- Closed HTTP gate refusal is known not submitted: installed controller persists
  CANCELLED/not_submitted and reconciles its own zero-fill reservation release.
- Fixture acknowledgement or unknown acceptance pauses the controller and retains
  its full reservation. It is NOT translated into a simulator execution or position.
- Partial fixture cancellation cannot release controller funds without the missing
  ownership linkage. Restart remains paused; no fabricated fills or automatic retry.

The held funds and mapping in these scenarios are SYNTHETIC, never verified real
cash or current contract eligibility. This package establishes linkage and refusal
semantics, NOT the complete real fill/exit pipeline.

## VM commands

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-controller-adapter-link/test_link.py
```

After tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-controller-adapter-link/demo.py \
  --output data/research/hilega-controller-adapter-link-demo-v1
result=$?
echo "Demo exit code: $result"
```

Use a new output directory. Unit tests and demo have not been executed during
authoring; only Python AST parsing was done. Dependency hashes match the runtime
and adapter source versions just validated on the VM. Do not edit hashes to bypass
mismatches; provide the diagnostic for review.

## Important result interpretation

The closed scenario releases a KNOWN UNSENT request only. It must not be extended
to an accepted timeout or a failed HTTP request with unknown outcome. Those retain
holds. The fixture scenario deliberately ends with a retained review-required hold
in its isolated database. This is expected fail-closed behavior, not a trading loss.

There are NO live checks, mutation calls or installation steps in this package.
The normal workspace should remain SIMULATION_ONLY, PAUSED and unfunded.

## Next promotion gates

1. Connect verified broker receipts, trades and positions to controller ownership
   reconciliation, including partial entry/cleanup SELL and external broker exits.
2. Prove real cash/reservation/debit accounting and current contract/quote evidence.
3. Stage a production broker port with all risk/control/health gates; don't replace
   SimBroker merely because this isolated link passed.
4. Complete daily loss limit, readiness/alerts, market-hours shadow observation and
   separately authorized controlled pilot. Real HTTP mutation behavior remains
   untested and the gate must remain closed until required integration is proven.
