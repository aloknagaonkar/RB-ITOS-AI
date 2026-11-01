# Reusable fixture-cycle API v1

## Stage and purpose

The reported 120-case three-cycle checkpoint is frozen. The next step replaces
numbered execution paths with one API for later fixture cycles. This package
does not deploy an execution worker or enable production orders.

Flow: fresh signal -> disabled preparation -> authorized fixture BUY -> fill
review -> owned-contract SELL -> terminal flat closeout -> signed local retirement
seal -> next fresh signal. Tests exercise the same API for a fourth cycle and
a bounded sequence reaching ten total cycles (the legacy three plus seven new).

## Run on the VM

Upload the ZIP into the checkout, then:

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-reusable-cycle-fixture-v1.zip
.venv/bin/python hilega-reusable-cycle-fixture-v1/apply_and_test.py --repo "$PWD"
```

Expected combined cases: **136** (the existing 120 plus 16 new cases). The runner
verifies semantic parity of the 25 checkpoint source files, checks the package
hashes, refuses differing existing targets, and adds eight new home files. It
runs the complete VM regression and writes VM-VALIDATION.json. Its PASS status
requires the expected full count, zero skips/failures and passing fourth/ten-cycle
sequence cases; a filtered or incomplete run is not reported as complete.

Syntax, source-generation, local import references and ZIP integrity were checked
here. Behavioral pytest execution is reserved for the user's VM. These candidates
are unverified until that VM run passes.

## Public API

`fixture_cycle_api` exports `prepare`, `buy`, `sell`, `closeout`, `retire`, and
`history`. All mutation paths require FIXTURE scope before file access. The
underlying implementation uses the existing tested preparation, single-use claim,
attempt, owned-price and closeout checks with generic tables and bindings.

- `fixture_cycle_history` authenticates the earlier two-cycle baseline and the
  signed third-cycle closeout/retirement. This legacy compatibility bootstrap is
  read-only. Original archives and numbered candidates are not rewritten.
- Each later retirement stores its cycle index, predecessor fingerprint, and
  distinct request/order/trade fingerprint contribution in the same transaction
  as exact local reference retirement. Original signed captures remain intact.
- The history reader validates order/trade preservation, exact new request and
  order ownership, durable attempts/receipts, sequence/predecessor bindings and
  terminal flat evidence. It builds one deterministic cumulative read view,
  rather than counting overlapping snapshots as separate disjoint V1 archives.
- Preparation, execution and exit use one authenticated prior-history view;
  retirement final validation reads the prefix before its own just-inserted
  record, avoiding a self-referential predecessor. Historical recovery reports
  recovery only and sends no additional order.

The seven implementation modules separate these concerns but are not numbered
per trade. Existing old-cycle test fixtures remain necessary for the bootstrap.

## Boundaries and next step

The policy remains one fully filled lot, fresh same-session evidence, positive
explicit fee buffer and premium plus buffer <= 50% of current verified available
cash. Only the SHA-pinned OFFLINE_FIXTURE adapter and fake broker transport are
accepted. UNKNOWN outcomes retain holds and never resubmit. Partial/cancelled
entry handling in this new generic path is not implemented or approved.

Test helpers explicitly update synthetic control/health timestamps and produce
synthetic fresh evidence. They do not demonstrate automatic production Resume,
actual broker debit attribution, fresh real network quotes, or live fill quality.
Tests cover the fourth and ten-total-cycle flows, delayed BUY recovery, uncertain
BUY/SELL recovery, concurrent BUY callers, retirement rollback, tampered chain,
current cash shortfall, and live scope rejection across all five mutation APIs.

No installed adapter, production gate, running service or production database is
changed. No token is requested. Tests write temporary synthetic databases.
Reservation release permission, production execution and readiness remain false.

After a passing VM result: integrate this reusable API with the durable fixture
journal consumer and test restart/event delivery across cycles. Production policy
and authority approval, actual read-only network validation, closed deployment,
operational drills and an explicitly authorized funded pilot remain separate.
Ten fixture cycles are finite correctness evidence, not unlimited live reliability.
