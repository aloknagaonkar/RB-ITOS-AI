# Third-entry admission candidate v1

This milestone adds **disabled third-entry preparation only** after two full,
closed fixture cycles and verified second-cycle reference retirement. It does
not submit a third BUY, implement a third SELL, enable production execution,
or modify installed services. Partial/cancelled historical cycles are excluded
from this initial two-full-cycle baseline.

## Run on the VM

Place the ZIP in the RB-ITOS-AI checkout, extract it into a new directory, then:

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-third-entry-admission-v1.zip
.venv/bin/python hilega-third-entry-admission-v1/apply_and_test.py --repo "$PWD"
```

Expected baseline: 67 existing cases plus 13 new cases = 80 cases, if existing
test files still match the reported counts. The runner uses the selected VM
Python interpreter. This package has received syntax, source-generation and ZIP
integrity checks here; behavioral pytest execution is reserved for your VM.
Paste failures before treating this milestone as verified.

## Changes

- `third_entry_history_candidate.py` authenticates the original first-cycle
  archive, second preparation proof, second closeout, and second retirement.
  It constructs one deterministic, fixture-signed cumulative baseline containing
  both cycles. It never inserts the cumulative snapshot into the original V1
  archive table or removes earlier history. The signed broker captures remain
  unchanged. One cumulative baseline is validated as two closed cycles.
- `third_entry_cash_candidate.py` retains the existing fresh cash, account-row,
  diagnostic, signal and half-cash budget checks, using that cumulative baseline.
- `third_entry_preparation_candidate.py` retains the verified atomic preparation
  logic in a separate module and admission table. It uses a dedicated THIRD
  binding model, so the older repeat-execution authorizer cannot silently treat
  it as a second-entry grant. It rechecks the cumulative baseline before commit.
- Tests cover bullish/bearish admission, disabled requests, preserved history,
  replay, three rollback checkpoints, current-cash shortfall, stale account
  capture, missing/tampered retirement, paused control, expiry and live-scope
  rejection. New preparation is exercised with fixture submission forbidden.

The runner validates semantic parity of three existing dependency sources
against the GitHub frozen checkpoint on feature/pcr-foundation:
`hilega-repeat-cycle-freeze-j6kig4dh`. It adds four new files under `$HOME` and
refuses to overwrite differing targets. Baseline files in this ZIP are for
comparison only; they are not installed. Existing VM fixture dependencies and
the staged, hash-pinned adapter remain required.

All database writes from candidate tests belong to temporary synthetic fixtures.
No production policies, fee completeness, broker cash release or live readiness
are established by these tests. `VM-VALIDATION.json` records the observed result.

The next milestone after a passing VM run is dedicated third-entry fixture
execution and recovery. Continued unattended trading is not established here.
