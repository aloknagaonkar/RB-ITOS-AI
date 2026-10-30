# One-shot ownership capture/persistence producer v1

Uses the already deployed account adapter and ownership-record functions. No runtime deployment or service restart is needed. This is a manual, one-shot producer, not a scheduled background service.

## VM commands

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-ownership-producer-v1.zip \
  hilega-ownership-producer-tools-v1

.venv/bin/python -W error::ResourceWarning -m unittest discover \
  -s hilega-ownership-producer-tools-v1 \
  -p 'test_producer.py' -v &&
PYTHONPATH=backend:. .venv/bin/python \
  hilega-ownership-producer-tools-v1/producer.py check &&
PYTHONPATH=backend:. .venv/bin/python \
  hilega-ownership-producer-tools-v1/producer.py record &&
PYTHONPATH=backend:. .venv/bin/python \
  hilega-ownership-producer-tools-v1/producer.py status &&
PYTHONPATH=backend:. .venv/bin/python check-preparation-paused.py
```

32 producer tests passed locally against exact reference copies of the deployed ownership module and validators. No live broker calls occurred in local tests. The CLI must still be exercised on your VM.

## Actions and side effects

- status: verifies the signed current record and local source fingerprint using a consistent read-only application/adapter snapshot. No broker GETs, token loading or database writes. Missing, stale or blocked records provide no current verified owned quantity.
- check: makes one fresh fixed GET-only pinned-account capture, checks the pin and before/after local snapshots, and runs the single-entry quantity review. No ownership database writes.
- record: makes its own NEW fresh capture, runs the same review, invokes the deployed transactional writer and verifies the signed current record by readback against the exact capture fingerprint. This action intentionally writes application ownership state/history/audit tables; they are created lazily if absent. It does not modify execution, cash reservation, broker adapter or controller tables.

Before the ownership tables first appear, record creates a consistent SQLite backup of the application database under a new private backups/hilega-ownership-producer-* directory. The backup file is mode 0600 and the directory 0700. The path is reported. This is a review/recovery backup, not permission to restore a whole application database over running services. No automatic database restoration is performed.

With the last reported empty account/history, expect:

- check: OWNERSHIP_PRODUCER_CHECK_COMPLETE with a blocked review and no verified owned quantity.
- record: OWNERSHIP_PRODUCER_RECORDED_BLOCKED, ownership_record_persisted=true and current_state_signature_verified=true.
- status: BLOCKED with the missing-entry/ack/fill reasons.

A valid BLOCKED record is the expected producer result for missing evidence. It does not establish zero strategy P&L and does not grant entry or exit permission. No real order is needed to validate this producer.

## Failure handling

If capture or review fails before persistence, record attempts to invalidate the current record with an explicitly labelled LOCAL producer-failure event. It never fabricates broker orders, fills, prices or balances. This requires the same readable pin and safe local account/paused scope. A changed/unavailable pin prevents that write; existing state cannot pass verification under a changed key, and the runtime freshness gate remains in effect.

An uncertain writer result or failed signed readback stops for review with persistence_outcome=UNKNOWN_REVIEW_REQUIRED and database_modified=null. There is no automatic write retry or broker request retry. Do not interpret null as confirmation that no write occurred. A confirmed invalidation reports OWNERSHIP_PRODUCER_FAILED_CURRENT_INVALIDATED and exits nonzero.

Public output contains bounded reasons, status, quantity, timestamps and the optional backup path. Tokens, raw account IDs, pin keys, order IDs, trade IDs and raw captures are not printed or saved by this script. The existing private pin and read-token configuration are reused.

## Operational limits

Only PAUSED / PREPARATION_ONLY / LIVE_CLOSED sources are accepted. Source staleness after the entry cutoff does not prevent an ownership read; it never supplies fresh entry admission. Installed and package code hashes are pinned to the completed ownership-record maintenance deployment. The code rejects mismatches rather than updating hashes silently.

There is no daemon or systemd change. No strategy Resume, order submission, SELL, cash-hold release, live fee attribution or P&L authority is introduced. Current scope remains one fully filled BUY entry, not a complete lifecycle fill ledger. The 50% entry allocation and no-required-daily-loss policy remain unchanged.

After records exist, use producer.py status plus check-preparation-paused.py for current checks. The previous maintenance package intentionally rejects nonempty ownership tables; its empty-state preflight is not a daily health check. Future code maintenance must preserve and assess those records rather than delete them to pass a preflight.

## Remaining go-live work

Successful VM producer validation completes manual population/invalidation of the deployed record. Automatic scheduling, if desired, is a separate explicit step. Full raw fill/lifecycle ownership, partial entry and SELL handling, live exit dispatch, complete fees/net P&L evidence, controlled reservation release, fresh eligible signal admission and the controlled broker pilot remain pending. All execution and release flags remain false.
