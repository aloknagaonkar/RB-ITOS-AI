# Third-cycle fixture reference retirement v1

## Current stage and purpose

The VM reported 108 passing cases including third BUY, SELL and verified flat
closeout. The third trade's five active local references still block a later
entry. This milestone retires those references only after a fresh terminal-flat
review. It preserves all earlier-cycle evidence, broker records and signed third
closeout. It does not assess broker cash release or authorize a fourth entry.

Flow: third BUY -> verified fill -> SELL -> verified flat -> signed closeout ->
**local reference retirement (this package)** -> later-cycle admission (pending).

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-third-reference-retirement-v1.zip
.venv/bin/python hilega-third-reference-retirement-v1/apply_and_test.py --repo "$PWD"
```

Expected combined cases: **120**, consisting of the existing 108 plus 12 new
cases. Behavioral execution is reserved for the user's VM. Syntax, source
generation and ZIP integrity checks here do not establish a behavioral pass.

## Scope

Adds two files under `$HOME`: fixture_third_retirement_candidate.py and
test_fixture_third_retirement_candidate.py. The installer verifies package
checksums and semantic parity of relevant baseline sources and refuses differing
existing targets. It runs the complete regression using the chosen interpreter
and writes VM-VALIDATION.json in this package folder. Baseline source copies are
comparison inputs only and are not installed.

The retirement transaction attaches the fixture execution DB read-only, requires
the signed third closeout and unchanged current source, authenticates the earlier
two-cycle cumulative history, rechecks fresh account evidence and terminal flat
state, seals an immutable record in fixture_third_reference_retirements and
deletes only the five active application references for that exact third entry.
It rechecks source, closure and earlier history before commit. Unknown outcomes
and insufficient closure proof remain blockers.

Historical replay does not require new capture freshness, but validates the
saved signature, closeout/history bindings and absence of reappeared references.
It reports fourth_entry_admission_assessed=false. It is not fresh trading
permission. Active-reference fingerprints and original closeout are preserved.

## Validation

Twelve cases cover preservation of three cycles and all broker DB tables,
idempotent historical replay, rollback at three checkpoints, expiry before
commit, stale capture, tampered retirement, tampered closeout, missing explicit
zero-position evidence, reappeared references and rejection of live scope before
database access. Existing candidate tests still run alongside these cases.

No installed adapter, production gate, running service or production database is
modified. All candidate DB writes in tests are to temporary synthetic fixtures.
Production execution and broker cash release permission remain false. A passing
result is evidence for fixture lifecycle correctness, not production readiness.

## Next milestone

After a passing VM run, freeze the three-cycle checkpoint and consolidate the
fixture lifecycle into reusable cycle handling. Fourth-entry admission and
continued-cycle proof are still pending; this package does not add a fourth
numbered execution path or establish unlimited repeat trading.
