# Exit-first reversal and partial-exit tracking: fixture v1

## Stage and why

The VM reported 152 passing cases for durable journal processing. This package
adds an explicit, bounded reversal/partial-exit policy in a new V2 consumer. An
opposite signal must not create overlapping exposure, and a partial SELL must not
be mistaken for flat or trigger an excess SELL.

Flow: combined EXIT/opposite ENTRY -> close the existing position -> verified
flat closeout and retirement -> audit the old opposite candidate as deferred ->
require a fresh post-Resume confirmation before a new opposite BUY.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-reversal-partial-fixture-v1.zip
.venv/bin/python hilega-reversal-partial-fixture-v1/apply_and_test.py --repo "$PWD"
```

Expected combined cases: **163** (the passing 152 plus 11 new cases). The runner
checks package hashes and semantic parity of 35 passing baseline files. It adds
only fixture_cycle_exit_v2.py, fixture_cycle_journal_v2.py and
test_fixture_reversal_partial.py under HOME, refuses differing existing targets,
and runs the full regression. VM-VALIDATION.json records the observed result;
complete PASS requires the full expected count, zero skips and key policy tests.

Syntax, helper imports and ZIP integrity were checked here. Behavioral execution
is reserved for your VM. These changes are unverified until that run passes.

## Implemented fixture policy

- V1 remains unchanged and still blocks combined reversal records. V2 is an
  explicit opt-in class, not an installed worker/service change.
- V2 selects the EXIT from an exact opposite-direction pair. It preserves the
  original journal record hash, sequence and confirmed event identity; it does
  not fabricate a replacement single-event journal or re-sign broker evidence.
- The existing exact-quantity SELL authorization, owned-price, freshness,
  durable-attempt and recovery checks remain in force. The new EXIT selector
  changes which original confirmed event is reviewed, not its identity.
- After flat closeout/retirement, a signed deferred-opposite receipt and cursor
  completion commit in one application transaction. The old opposite signal is
  not submitted. A later, genuinely fresh post-Resume confirmation goes through
  the unchanged preparation/cash/control/BUY gates. No auto-Resume is added.
- A pending or partially filled working SELL holds the cursor and reports filled,
  remaining and pending quantities. Signed progress persists the observed fill
  quantity; a later regression is rejected. Restart/poll recovery reuses the
  durable attempt without new quote capture or another SELL.
- If a terminal cancellation leaves residual quantity, V2 reports
  EXIT_TERMINAL_RESIDUAL_REVIEW_REQUIRED and retains the hold/cursor. It does not
  automatically cancel, reprice or resubmit a residual SELL. Unknown outcomes
  continue to block closeout and opposite entry.

Partial unit quantities and cancellations in these tests are synthetic stress
cases, not verified real exchange/broker fill behavior or production policy.

## New cases

Eleven cases cover exit-first reversal plus fresh opposite confirmation,
retirement/cursor restart without opposite submission, partial-fill progress
through a long wait and restart, partial reversal blocking, fill regression,
cancelled partial residual review, unknown reversal SELL, wrong-parent reversal,
and live-scope rejection for the consumer/SELL/closeout paths.

Prior working-order and closeout tests still run. Test helpers explicitly manage
synthetic fills, evidence and controller/health timestamps. No real token, network
order, service hook, production runtime or production database is involved.
Production execution and reservation release permission remain false.

## Remaining work

Immediate same-signal opposite BUY continuation remains disabled to preserve the
existing Pause/Resume and pre-Resume signal guards. Automatic residual handling,
cancel/reprice policy and partial-entry execution remain pending. After a passing
VM result, decide/test those fixture policies as needed before packaging a closed
operational worker hook. Production authority/policy approval, real read-only
network checks, closed deployment and a funded authorized live pilot are separate.
