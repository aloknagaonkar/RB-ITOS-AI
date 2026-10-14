# HILEGA ATM ±5 research-only update

Extract into ~/RB-ITOS-AI. This package requires the installed strike-safety update
and touches only two research scripts, two research test files and one new document.
Sandbox execution remains ATM ±2. Ranking observation also stays ATM ±2. No policy,
worker, backend runtime, .env, control, API/frontend or 14:55 cutoff changes occur.
No local tests, application Python or frontend build were run.

## Verify on the VM before installing

```bash
python hilega_atm5_research_update/install.py --check
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega_atm5_research_update/files/tests
```

A source-hash mismatch requires review; do not bypass it. The staged test loader
uses patched research modules and unchanged installed backend dependencies.

After tests pass:

```bash
python hilega_atm5_research_update/install.py
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  tests/test_hilega_strike_ranking_research.py \
  tests/test_hilega_atm5_coverage.py
```

The installer makes a backup. No worker stop, service restart or frontend build is
needed for this offline-only update.

## Run coverage

Confirm your replay strategy version; the default below matches the intended
pending-switch strategy. A mismatch is an error, not a reason to relax validation.

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/research_hilega_atm5_coverage.py \
  --expected-version five-minute-setup-1.2.0-pending-switch \
  --output /tmp/hilega-atm5-coverage.json
```

Share the printed summary. The full JSON includes all eleven candidate paths per
trade, missing contracts/minutes, ambiguous keys/conflicts and cache source files.
No broker calls are made. Complete path means cache evidence only: nearest eligible
expiry, historical lot size, bid/ask, Greeks and actual fills remain unverified.
Nearest cached expiry is labelled as such; it cannot approve a trading policy.

The strict net-comparison tool additionally supports --wings 5, defaulting to the
existing --wings 2 behavior. It needs a verified eleven-contract manifest and
explicit cost/slippage assumptions before making meaningful price comparisons.
Read docs/hilega-atm5-research.md for details.
