# November historical replay population

Audits expected elapsed November 2026 sessions using the deployed reviewed
calendar; distinguishes missing/invalid NIFTY one-minute candle caches, missing
20-session warmup inputs, absent/stale replay artifacts, and UI registry absence.
The deployed historical registry lists saved replay artifacts, not every warmup
cache date. A candle cache alone does not guarantee a selectable replay session.

From the VM repository root:

```bash
.venv/bin/python -u -B hilega-november-data-v1/populate.py \
  --through 2026-11-23 --populate
```

Omit `--populate` for an audit-only run. Reports are always new timestamped files
under `data/recovery/hilega-november-validation-*`.

Population fetches only missing/invalid candle inputs via the existing Upstox
historical GET source. Validated additions go to the already recognised dedicated
verified cache root. Legacy cache files remain unchanged. If a corrupt dedicated
cache needs replacement, the existing deployed helper preserves its original
bytes in a SHA256-named archive first. Valid existing inputs are reused.

Then the existing 3.0.2 runner loads/generates results for each supported complete
session, using exactly 20 verified prior sessions. Existing matching artifacts
are fingerprint-validated; stale research artifacts are archived by the deployed
loader before regeneration. Frozen/live evidence is not rewritten. Results use
the same research output directory already scanned by the historical session
registry; no fabricated registry marker files are created.

The tool does not install/modify application source, restart services, alter
strategy rules, create option fills, edit live journals/databases or submit orders.
It reads `.env` only when data recovery requires an Upstox token; tokens are not
printed or copied into reports. Client acquisition is limited to historical
candle reads. It does not fetch option premiums.

## Shortened 8 November session

The deployed calendar validates its 70 minutes. Its complete regular-grid bars
can seed later sessions. However, the current deployed target replay runner
requires 375 target minutes. This utility recovers/preserves the 70 real minutes
and reports SPECIAL_TARGET_REPLAY_UNSUPPORTED rather than padding candles or
publishing a misleading COMPLETE artifact. It remains a separate follow-up item
for target replay support. It must not be counted as a full normal session.

## Output and resuming

The terminal first lists all target dates and initial missing inputs/UI status.
It then prints recovery/replay progress by date, including net, peak positive
points and giveback. The report JSON is checkpointed after every item. Rerunning
reuses valid saved data/results and retries unfinished items. POPULATION_COMPLETE
is emitted only with no remaining items; otherwise the exact remaining list is
printed. Registry errors remain explicit and never imply confirmed UI readiness.

Warmup may require additional October sessions for early November dates. Future
dates and incomplete current sessions are rejected. Today's full session may be
requested only after 15:35 IST. Refresh historical replay after the run and select
the current combined/alignment replay source. Research NIFTY points exclude
option fills, fees and slippage; they are not live execution results.

Paste the printed summary and `cat <REPORT path>` result for review. If token/data
recovery fails, the report preserves all successes and identifies remaining
inputs without printing credential-bearing exception details.
