# Application lifecycle candidate — combined integration bundle v1

## What this connects

Actual application Source (synthetic signed inputs) -> existing preparation -> durable closed handoff -> candidate adopted BUY -> intercepted acknowledgement -> signed account orders/trades/position reconciliation -> actual Source closed EXIT record -> explicitly invoked SELL candidate -> atomic request/claim/attempt -> intercepted acknowledgement -> working/partial/full SELL observations -> explicit signed flat reference.

This is isolated candidate code and synthetic VM validation. It does not connect itself to the running worker, open the broker gate, or automatically consume REFUSED_CLOSED records. An EXIT is explicitly reviewed by the candidate API with an independent synthetic authority and fresh signed account/market evidence. The original dispatch remains REFUSED_CLOSED with automatic_execution_eligible=false. No opposite BUY is submitted on reversal.

## VM commands

```bash
cd ~/RB-ITOS-AI
unzip hilega-application-lifecycle-candidate-v1.zip
.venv/bin/python hilega-application-lifecycle-candidate-v1/apply_and_test.py --repo "$PWD"
```

Default expected: 79 cases (the prior 49 handoff/attempt integration cases plus 30 new lifecycle cases). Optional --new-only runs the 30 new cases. The default is the preferred combined milestone check. Neither option is the full 163-case prior fixture suite or the complete repository release regression.

The runner requires the prior existing-request-attempt VM report with 49 cases and broader_handoff_integration_reexecuted=true. It checks 15 exact reviewed application/test source pins. Source differs -> stop and return the filename; do not edit pins. Folder-local modules/tests only: no HOME installation, installed source replacement, unit writes or service restarts. Tests use temporary synthetic databases and intercept gate and transport for positive order branches. Mock token providers fail if accessed.

Only Python syntax, declared test enumeration, package hashes and ZIP integrity were checked during artifact creation. Behavioral pytest runs are left to your VM. VM-VALIDATION.json is written after the VM run; no result is pre-created.

## Why this change is needed

An acknowledgement does not prove a fill or position. The SELL quantity must follow signed trades matching the exact acknowledged BUY, with an explicit position row and unchanged application hold/request provenance. Missing positions, unrelated orders/exposure, wrong quantities, modified receipts and UNKNOWN entry outcomes block ownership reference creation.

Before any new SELL, this candidate requires a full terminal BUY and exactly one owned lot. It links the EXIT to the parent entry timestamp, verifies the journal chain and consumed Source references, and checks the persisted closed EXIT boundary. It prices only the owned contract at its fresh reviewed bid. Entry cash, current ATM selection and the entry clock window are not required for this protective exit review. Current event freshness, same-session identity, controller version, quote quality and independent candidate authorization remain required. Policy approval and actual execution clearance remain false.

The SELL request, signed application adoption, signed adapter claim and adapter attempt are committed together in an attached DELETE-journal/FULL-synchronous transaction on the same filesystem. Recovery validates signed adoption and wire/attempt links, then binds a durable receipt or stays UNKNOWN; it never resends. Existing residual SELL exposure cannot create an automatic extra order. Position observations are signed, monotonic and idempotent; a missing position row is never treated as flat.

## New test coverage (30 cases)

- Actual Source preparation + adopted BUY + signed full-fill quantity.
- Actual Source EXIT + bid-priced candidate SELL + signed explicit flat reference.
- Real gate refuses before new exit capture, request or attempt.
- Open/partial BUY refuses SELL; missing/forged positions and unrelated exposure block review.
- Modified receipt provenance and UNKNOWN BUY block ownership assumptions.
- Exit-first reversal creates no opposite BUY.
- Two pre-commit failure points roll back SELL request/claim/attempt together.
- Three post-commit interruption points recover without capture or send.
- Lost SELL response stays UNKNOWN; concurrent callers submit once.
- Working/partial fills preserve remaining quantity; terminal partial cancellation requires residual review.
- Fill regression, observation replay and observation interruption handling.
- Stale quote, expired claim and tampered closed EXIT dispatch block submission.
- Flat requires an explicit position row; owned exit needs no funds/ATM inputs.
- 14:55 protective EXIT is not limited by the entry clock; partial tracking accepts fresh captures after a long wait.

## Limits and next gates

First adopted application lifecycle only: account order sets are strict; historical multi-cycle production adoption is not integrated. Partial entry cancellation/resizing is not implemented here. Partial SELL is observed without automatic residual resubmission or cancel/reprice. A signed flat reference is not a financial closeout or permission to release holds. Actual fees/net P&L remain incomplete and never gate these protective exit checks. All existing local preparation references remain retained.

Account evidence and observation signatures use the existing local account key. Adoption/claim signatures use a distinct caller-provided candidate key; trusted production authority provisioning, approved pricing/partial policies and live ARMED dispatch authority are not implemented. Journal hash-chain checks are not external authentication. Local transactions do not provide atomicity with the remote broker or external journal writer. The Source itself retains closed dispatch semantics. Running-service integration, dependency/release reconciliation, full regression, managed deployment/rollback, actual broker validation and an authorized funded pilot remain pending.

Output report distinguishes candidate implementation from production enablement/deployment. Source and service states stay unchanged. Production execution and readiness remain false.
