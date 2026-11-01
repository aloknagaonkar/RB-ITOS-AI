# Three-cycle source checkpoint

## Stage and purpose

The VM reported 120 passing cases, including third BUY, SELL, flat closeout and
local-reference retirement. This utility freezes the known source baseline before
consolidating reusable cycle handling. It does not add fourth-entry permission.

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-three-cycle-checkpoint-v1.zip
.venv/bin/python hilega-three-cycle-checkpoint-v1/freeze.py --repo "$PWD"
```

The utility checks the existing 120-case VM report, verifies semantic parity of
25 candidate/test files against the delivered passing sources, copies those
sources plus directly imported home Python helpers and the hash-pinned fixture
adapter into a new checkpoint folder, and seals a SHA-256 manifest. Whitespace
and comment differences are accepted; changed Python statements are refused.

It opens no databases, requests no token, performs no broker requests, does not
run pytest again, and changes no candidate source or service. It does not copy
.env files, tokens or database files. All created files are source/checkpoint
artifacts beneath a new hilega-three-cycle-freeze-* directory in the checkout.

This is a source checkpoint, not a standalone deployment bundle. Repository
runtime dependencies and pinned external collector resources remain necessary.
The existing PASS report is preserved as prior VM evidence; the utility does not
claim a new behavioral test run or exact test-input hashing at the prior run.

Production execution, runtime deployment and production readiness remain false.
The next milestone is specified in CONSOLIDATION_PLAN.md. Existing numbered
fixture candidates remain comparison evidence, not a general repeated-trading
runtime. No fourth-entry admission is implemented by this package.
