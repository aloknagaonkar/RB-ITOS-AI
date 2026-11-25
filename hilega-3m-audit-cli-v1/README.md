# Hilega per-candle audit reader

Standalone read-only CLI for the Hilega completed 3-minute journal, including
`bullish-gap2-full-wma2-3.0.2-3m-bounded-warmup`. Uses Python standard library only.
No app installation, database edits, service changes, broker calls or replay run.

From `~/RB-ITOS-AI`:

```bash
.venv/bin/python -u -B hilega-3m-audit-cli-v1/audit_3m.py \
  --day 2026-11-23 \
  --version bullish-gap2-full-wma2-3.0.2-3m-bounded-warmup
```

The terminal gives one row per direction per recorded boundary and prints the
result ZIP path. Open `audit.html` locally for expandable details, or `audit.csv`
in a spreadsheet. `audit.txt` contains full readable details; `audit.json`
retains original records, duplicates, monitor checks and supplemental events.
Share the generated result ZIP for analysis. It contains strategy audit records;
the reader does not read `.env`, tokens or account credentials.

For complete details in the terminal over a shorter window:

```bash
.venv/bin/python -u -B hilega-3m-audit-cli-v1/audit_3m.py \
  --day 2026-11-23 \
  --version bullish-gap2-full-wma2-3.0.2-3m-bounded-warmup \
  --from-time 09:18 --to-time 10:00 --detail
```

Optional: `--live-only` excludes reconstructed decisions. `--version latest`
(default) selects the last version encountered in that day's journal, not a
semantic-version comparison. Pin a version to compare consistent policy rules.
Use `--audit /absolute/path/to/step-audit.jsonl` for a non-default source, or
`--repo /absolute/path/to/RB-ITOS-AI` when running outside the repo root.
Use `--out /path/to/report-parent` to change output location. Every invocation
creates a new timestamped report folder and ZIP under `/tmp/hilega-3m-audits` by
default. Copy result ZIPs somewhere durable if needed after a VM reboot.

## Reading each boundary

* Decision time is IST: 09:18 evaluates the 09:15–09:17 candle.
* Both bullish and bearish rows include RSI9, EMA3(RSI), WMA21(RSI), price EMA10,
  complete candle OHLC, current/previous gap, expansion and directional strength.
* Recorded flags and blockers describe actual engine evaluations. `WAIT` or
  `EMA10_ENTRY_WAIT` includes the recorded reason; a next-candle wait is timing,
  not a failed directional vote. Both attempts are retained when a boundary has
  a failed follow-up followed by a new setup.
* Calculated diagnostics describe each direction even without a candidate.
  These are labelled separately and do not prove why the engine rejected a trade.
* `NOT_EVALUATED` means no evaluation was recorded, not FAIL. Existing ownership,
  missing fresh alignment and unavailable watch/manual evidence are distinguished.
* Strength uses any 2 of 3 votes: positive directional gap, directional WMA
  movement at least 0.75, and gap expansion. Not every failed flag blocks entry.
* A follow-up requires colour and RSI direction plus PRICE or fresh checks;
  the PRICE route can pass with fewer than two new strength/gap votes.
* Bullish initial gap/full-WMA checks appear where evaluated. Initial setup and
  follow-up requirements differ; irrelevant checks remain NOT_EVALUATED.
* The bullish reversal monitor is separate from the ordinary entry gate. Its
  checks and actual trade/exit events are retained.
* LIVE_RECORDED means forward processing recorded by the app, not a broker fill.
  RECONSTRUCTED means retrospective recovery. Forward evidence takes precedence
  over a later reconstructed duplicate, with all duplicates preserved in JSON.
* Versions are not merged. Today's repaired morning records can be reconstructed;
  they do not prove the repaired policy actually traded before installation.

## Coverage and limits

The reader snapshots the complete-line prefix present when the file is opened;
it ignores a partial final line while the worker is appending. It records the
prefix size/hash and malformed-line count. It does not certify the journal hash
chain. Missing regular-session boundaries are listed explicitly; no rows or
blockers are fabricated. A candle just completed may still be processing.
Coverage expectations use the normal 09:15–15:30 session; for shortened/special
sessions the absence list is informational. A 15:30 forced exit can appear in
the supplemental session-close records rather than the decision trade events.

This reads existing engine evidence; it does not fetch fresh candles, recompute
strategy state or change the deployed strategy. Historical days without 3-minute
records for the selected version require a separate fresh replay audit. Raw
records with non-finite numbers fail JSON export rather than silently changing
their evidence.

## Verify reader

```bash
.venv/bin/python -B -m unittest discover -s hilega-3m-audit-cli-v1/tests
```

Tests cover version separation, forward/recovered precedence, absent evaluations,
bearish signs, completed-candle provenance, next-candle waiting, PRICE follow-up,
reversal-monitor entries, multiple attempts, exit flags, file snapshot handling,
HTML escaping and end-to-end export without modifying the input journal.
