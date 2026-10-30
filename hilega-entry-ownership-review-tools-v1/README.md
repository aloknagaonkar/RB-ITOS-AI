# Current entry ownership review v1

Read-only review of one current-session, fully filled BUY entry. This is not a deployment, ownership-ledger migration or live exit executor.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-entry-ownership-review-v1.zip \
  hilega-entry-ownership-review-tools-v1

.venv/bin/python -W error::ResourceWarning -m unittest discover \
  -s hilega-entry-ownership-review-tools-v1 \
  -p 'test_*.py' -v &&
PYTHONPATH=backend:. .venv/bin/python \
  hilega-entry-ownership-review-tools-v1/check.py check --capture-account \
  --repo "$PWD"
```

Uses the existing private account pin and read token configuration. Never paste tokens, account captures or private pin contents into chat. The public JSON contains counts, reviewed quantity, timestamps and bounded reasons, with no raw account/order/trade IDs.

The CLI pins the code versions deployed after closed exit-dispatch maintenance. It rejects changed installed sources or package files rather than silently updating expected hashes.

## What is checked

- Local application and closed-adapter data are read in one attached read-only SQLite transaction. That snapshot now includes cash reservations, cash policy, stop state, source cursors and closed exit records.
- Before and after a fresh fixed GET-only account capture, local snapshots and the private pin must match. This detects observed changes; it is not atomicity with the remote broker or a guarantee against a change followed by restoration between reads.
- Current account identity, local HMAC, profile checks and a maximum 30-second age are verified.
- Existing application plan/hold/outbox/request binding hashes and durable PLACE receipt references must match the current order and actual trade quantities. Symbols or tags never establish ownership.
- The signed application cash reservation is checked against those exact hashes, its retained state and 50% policy.
- Historical outer bundle and nested cash signatures, account scope, historical capture window, no-activity baseline, stable available-cash field and original half-cash cap are authenticated. Historical cash is not reused as current entry capacity.
- Exactly one fully filled BUY entry is supported. Its explicit current position row must equal the fill quantity. Missing rows are not assumed flat. Extra requests, orders, attempts, unrelated exposure, SELL activity, partial/nonterminal entries, unknown outcomes or prior-session links block the review.

## Interpretation

On the current empty account/history, expect BLOCKED_ENTRY_OWNERSHIP_GAPS and reviewed_remaining_entry_quantity=null. Empty history does not establish zero strategy P&L. Do not create an order merely to obtain a passing result.

If an eligible bound entry exists in the future, CURRENT_ENTRY_QUANTITY_RECONCILED_READ_ONLY describes that single current entry quantity under the above scope. It is never an exit admission or a permission to sell. Fixture tests report FIXTURE_ENTRY_QUANTITY_RECONCILED and never claim live ownership verification.

The result does not persist an ownership ledger, integrate the production exit lifecycle, assess order modification history or revalidate current contract/quote pricing. Aggregate fee evidence remains insufficient for strategy fee attribution. Net P&L, full lifecycle ownership, real broker cash locking, entry permission and reservation release remain unverified/disabled. The current BUY-entry quantity review is narrower than those requirements.

## Validation

113 local component tests passed during packaging: the existing 85 bridge/reference tests plus 28 new ownership and capture-barrier tests. No broker calls were made locally. The live capture command must still run on the VM. The tests cover nested-signature tampering, missing/unknown reservations, policy mismatch, partial fills, missing position rows, unrelated orders, stop state, source changes, empty history and database/input immutability.

No running services, application databases, configuration, controller state or execution route are changed. The entry policy remains 50% of verified available cash with no required daily loss limit. Production mutations remain closed in code.
