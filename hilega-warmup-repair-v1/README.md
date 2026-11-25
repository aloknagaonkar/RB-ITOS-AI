# Hilega warmup coverage repair — 23 November 2026

This is a follow-up to the successfully installed 19-November three-minute
rollout, not a replacement of the original strategy requirements. It updates
the version to `bullish-gap2-full-wma2-3.0.1-3m-warmup-freshness`.

## What changes

* Require all 20 expected prior trading sessions, including the most recent
  expected session. A count of 520 old sessions no longer satisfies readiness.
* Before live bootstrap, recover missing/invalid recent sessions using historical
  NIFTY candle reads. Validate the instrument, date, exact timestamps, uniqueness,
  OHLC, and volume before using or storing them. An empty response on an expected
  trading session blocks startup; it is not guessed to be a holiday.
* Store recovered candles only in
  `data/historical-evidence/hilega-3m-warmup-verified-v1`, with precedence over the
  three older roots. Preserve all original cache files. Atomic recovery retains
  previous bytes if a corrupt dedicated cache needs replacement.
* Share freshness checks and warmup aggregation between live and historical
  replay, including direct `replay()` calls. Old replay outputs are invalidated
  by the source/version fingerprint and retained in the existing archive flow.
* Recognize the reviewed 8-November-2026 Muhurat session as 70 exact minutes from
  14:20 through 15:29. Keep the engine's existing 09:15-anchored grid: omit the
  incomplete leading bucket's single 14:20 minute and seed 23 complete bars from
  14:21 through 15:29. Never synthesize the missing morning or carry prices
  forward. This is the explicit research convention used in the reviewed rerun;
  it is not a claim that all chart vendors anchor special-session bars this way.
* A current dashboard read labels prior-session/prior-version ACTIVE or
  PENDING_EXACT_EXIT observations `UNRESOLVED_HISTORICAL`, retaining their
  `recorded_status`, prices and missing exit evidence. They remain visible, with
  reconciliation required, but no longer count as today's active trades. No
  exit, broker flat state, realized P&L, or historical closure is fabricated.

Entry votes, EMA10 checks, RSI levels, follow-up checks and exit rules are unchanged.
No order submission/cancellation, broker execution activation, .env edits,
frontend rebuild, database edits or unit-file changes are included.

## Calendar scope and source

The reviewed calendar supports 2026 only. New years fail with
`WARMUP_CALENDAR_YEAR_NOT_REVIEWED` until reviewed calendar data is supplied.
The 2026 listed cash-market holidays and the special 8-November session are
explicit data, not weekend-only guesses:

* https://www.nseindia.com/resources/exchange-communication-holidays
* https://nsearchives.nseindia.com/content/circulars/CMTR76941.pdf

Unexpected closures or special-session coverage fail validation for review.
Historical replay still requires a full regular 375-minute target session;
this repair adds special-session handling to warmup, not special-day trading.

## Prepare on the VM now

Extract in the repository and run:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -u -B hilega-warmup-repair-v1/repair.py --prepare
```

Preparation checks the exact installed source and current companion hash chain,
builds an isolated candidate backend, runs all bundled VM tests and both
companion integrity checks, recovers the recent sessions into
`/tmp/hilega-warmup-repair-v1/verified-candles`, and prints a fresh research replay
through the latest completed minute. It does not stop services or install files.
Tests run with the VM virtual environment. Package creation performed static
Python syntax/source-pin checks only; no VM test result is claimed in advance.

The default preparation work area is `/tmp/hilega-warmup-repair-v1`. Override it
with the same `--work /absolute/path` for both phases. Outputs are
`today-research.json` and `preparation.json`. Research output is not actual live
trade history, and peak points are hindsight one-minute extremes before costs.
The same work area reuses already validated recovered candles on repeated prepares.

The installer stops on any source mismatch. Do not force hashes, overwrite
current source manually, or bypass the companion check. Share the named mismatch
for review if the VM has newer changes.

## Controlled installation after the session is flat

After 15:35 IST, run:

```bash
.venv/bin/python -u -B hilega-warmup-repair-v1/repair.py --apply
```

Apply requires today's successful preparation tied to these exact candidate
hashes, and reruns the VM tests/integrity preview before stopping anything.
It requires today's completed cutoff audit, no current underlying trade,
no unsettled current-session option observation, no open/pending/uncertain
sandbox ledger state and no active execution workers. Old unresolved historical
observations stay explicitly unresolved; they are not interpreted as verified
broker positions or closed by this rollout.

It backs up all ten changed/added source files under
`data/deployments/hilega-warmup-...`, stops only the originally active API,
reference companion, observation analytics and readiness units, installs exact
reviewed sources and the prepared dedicated candle files, checks the updated
companion, and restarts those same units. The existing 15:30 worker dispatch
patch is preserved unchanged. The two execution services and SQLite bridge
services are not started or restarted.

Success is `WARMUP_REPAIR_DEPLOYED`, after verifying the new API version, fresh
worker bootstrap with current warmup coverage, fresh component health and a new
policy flat cutoff state. Source/integrity/startup failures trigger source
rollback and restart of the previous services. Original caches, audit journals,
databases and frontend assets are never restored or rewritten by the installer.
Normal application startup can append audit/recovery evidence.

The companion integrity inventory changes from 414 to 416 files. Five reviewed
runtime hashes change, two new helper files are added, and 409 runtime hashes
remain unchanged. The manifest, CLI manifest anchor and service CLI anchor are
reissued as one exact reviewed set. No integrity checks or authority restrictions
are disabled. All three files are included in source backup/rollback.

## Manual source rollback

Use the exact successful backup printed by apply, after a verified flat close:

```bash
.venv/bin/python -B hilega-warmup-repair-v1/repair.py \
  --rollback /absolute/path/to/the/successful/backup
```

Rollback refuses newer source changes and retains candle recovery files and
journals. It restores the preceding source policy, which does not consume the
new dedicated warmup root; inspect readiness rather than assuming the stale
policy is repaired by rollback.
