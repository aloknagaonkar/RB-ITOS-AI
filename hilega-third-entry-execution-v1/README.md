# Third-entry fixture execution v1

Adds a dedicated third-BUY fixture execution module and ten test cases to the
reported passing 80-case baseline. Expected combined count: **90**, if the
existing files retain those counts. Behavioral tests are reserved for the user's
VM. Syntax and ZIP integrity checks here do not establish a behavioral pass.

## Run

Place the ZIP in the RB-ITOS-AI checkout and run:

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-third-entry-execution-v1.zip
.venv/bin/python hilega-third-entry-execution-v1/apply_and_test.py --repo "$PWD"
```

The runner verifies package hashes and semantic parity of the existing repeat
execution, third-entry candidates and corrected third-preparation tests. It adds
only `$HOME/fixture_third_execution_candidate.py` and
`$HOME/test_fixture_third_execution_candidate.py`, refusing to overwrite differing
files, then runs the full regression. It writes the result to VM-VALIDATION.json
inside this extracted package. The prior third-entry diagnostics correction must
already be applied, as in the reported 80-case passing VM run.

## Execution contract

The new executor derives from the frozen repeat-entry executor. It uses the
dedicated third admission table/binding and authenticates the two-cycle cumulative
history through `load_closed_history`. Fresh account, cash and market evidence,
held-budget references, exact request/wire, control/session and current database
context are rechecked before the single-use authorization claim commits with the
attempt. Only the exact SHA-pinned OFFLINE_FIXTURE adapter and its fake transport
are accepted. FIXTURE scope is required before accessing files.

Durable attempt recovery does not request new captures or send another BUY.
Acceptance followed by a lost response stays UNKNOWN and retains the hold.

Tests cover bullish/bearish third BUY with previous requests/orders preserved,
delayed recovery, exact grant expiry, claim rollback, fresh cash shortfall,
lost-response recovery, tampered admission, concurrent callers and live-scope
rejection before file access. Fixture acknowledgment is not a verified fill.

No installed adapter, production gate, running service or production database is
modified. The third SELL/closeout, further-cycle reuse, production authorization,
deployment and live pilot remain pending. This package grants no production
permission and does not establish production readiness.
