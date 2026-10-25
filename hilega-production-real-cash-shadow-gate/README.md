# Real-cash input and isolated shadow reservation gate

Standalone read-only/shadow milestone. No install/apply, services or strategy changes.
No Upstox order transport, trading permission, application simulator update or
live reservation writes. Its optional shadow book is separate from all app ledgers.

## What this establishes

Fresh signed account-pinned captures from the validated read-only cash collector
are verified for scope, signature, session, capture window, completeness and age.
Only the net cash field is used; no pledge balance, margin-used addback or assumed
per-order reflected premium is credited. The cap is 50% of current net cash,
rounded down. A proposal cost rounds up and includes any caller-specified buffer.

The gate rejects shadow proposals when account orders/fills or nonzero positions
lack ownership mapping, funds change during capture, diagnostics need review, cash
is absent, holds exceed capacity, or a local outcome is unknown. Merely observing
an empty account never releases an unknown hold. Restart retains all holds.
Concurrent shadow proposals share a single BEGIN IMMEDIATE budget transaction.

Full holds are conservatively deducted from half of current broker net cash.
This CAN double-count an already-reflected debit and block affordable proposals.
The report explicitly marks that uncertainty. This package DOES NOT solve real
per-order debit attribution; it never treats conservative capacity as production
approval. The goal is a durable fail-closed gate ready for verified attribution,
not silently assuming that missing attribution equals reflected cash.

## VM validation

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-real-cash-shadow-gate/test_gate.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-real-cash-shadow-gate/demo.py \
  --output data/research/hilega-real-cash-shadow-demo-v1
```

After tests/demo pass, capture current account evidence:

```bash
PYTHONPATH=backend:. .venv/bin/python \
  hilega-production-real-cash-shadow-gate/read.py \
  --env-file .env \
  --output data/research/hilega-real-cash-shadow-read-v1
result=$?
echo "Read-only exit code: $result"
```

No proposed cost is needed for the first capture. Terminal output omits cash
amounts, raw account IDs and tokens. The owner-only report.json holds cash values.
Exit 0 means fresh read-only shadow capacity exists; it does NOT mean entry is
permitted. Exit 2 means blocked/review/no capacity; read reason/reasons. In
particular zero cash is a legitimate no-capacity result, not an authentication
failure. Do not deposit funds solely to make this test pass.

Default isolated book: data/research/hilega-real-cash-shadow/shadow.sqlite.
A fresh output directory is needed for each run. Installed dependency hashes
are checked; never edit the manifest merely to bypass a mismatch.

## Optional explicit shadow proposal

Add --proposed-cost 6600.00 for an illustrative all-in proposal preview. This
number is NOT a current quoted contract cost. A real contract-price/quantity
mapping and quote freshness gate remain separate pending work. Add
--shadow-plan-id unique-name only to deliberately retain an isolated shadow hold;
no application reservation or actual order is created. Read-only captures alone
do not create holds. There is no automatic hold expiry or live-flat release API.
Only an explicitly never-submitted shadow proposal can be cancelled with the
library method; unknown holds remain for review.

## Remaining production prerequisites

Real acknowledgement/fill ownership and attributable debit evidence; validated
cash/reflection accounting; actual broker transport; external exits; market-hours
quote checks; daily loss limit; alerts and controlled pilot. Account activity
requires review even if completed positions appear flat. No UI promotion here.
Tests and demo have NOT run in the authoring workspace; only AST parsing was done.
