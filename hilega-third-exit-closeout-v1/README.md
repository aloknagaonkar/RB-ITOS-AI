# Third-position SELL and closeout candidate v1

Adds third-position fixture SELL and signed flat closeout to the reported
90-case passing baseline. There are **18 new cases**, for an expected combined
**108 cases** if the existing test files retain their reported counts.

## Run on your VM

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-third-exit-closeout-v1.zip
.venv/bin/python hilega-third-exit-closeout-v1/apply_and_test.py --repo "$PWD"
```

The runner validates package checksums and semantic parity of relevant existing
candidate/test sources. It adds only two new home files:
`fixture_third_exit_candidate.py` and `test_fixture_third_exit_candidate.py`.
It refuses to overwrite differing files and runs the full regression with the
selected VM Python. Observed results are written to VM-VALIDATION.json.

## Contract and boundaries

The executor derives from the frozen second-exit implementation, uses the
dedicated third-entry preparation proof, and authenticates the cumulative
history of both earlier cycles. It requires an exact fully filled one-lot third
BUY and an exact linked strategy EXIT event. A partial entry is blocked and its
hold remains retained; no partial-quantity policy is introduced.

Owned-contract signed account and market captures determine a bid-priced LIMIT
SELL without requiring fresh cash or a new current-ATM selection. The grant,
request/wire, position, price and fresh source context are checked again in the
attempt transaction. Only the SHA-pinned OFFLINE_FIXTURE adapter is accepted.

Recovery uses durable attempts/receipts without another capture or submission.
A lost response remains UNKNOWN. Signed terminal-flat closeout is stored in the
separate fixture_third_position_closeouts table; old V1 archives, second closeout
and second retirement records are not rewritten. Third active references remain
retained, fees_complete stays false and reservation release permission stays false.

Tests exercise prior-cycle request preservation, exact third SELL quantity,
terminal flat closeout and replay, delayed recovery, two closeout rollback
checkpoints, open-position rejection, tampered closeout rejection, lost response,
claim rollback, stale quote, missing explicit zero-position evidence, exact claim
expiry, closeout expiry, concurrent callers, unsupported partial entry and live
scope rejection before file access.

Syntax/source-generation and ZIP integrity were checked here. Behavioral pytest
execution is reserved for your VM. No installed trading runtime, production gate,
running service or production database is modified by this package. Fixtures use
temporary synthetic databases. No broker order is submitted by this candidate.

Third-cycle reference retirement, fourth-entry admission, general repeat-cycle
integration, production policies/authority, execution deployment and an explicitly
authorized live pilot remain pending. A passing fixture result does not establish
production readiness or fill performance.
