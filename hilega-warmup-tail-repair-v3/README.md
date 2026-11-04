# Warmup repair and prevention v3

Run on VM from the repository root:

.venv/bin/python -B hilega-warmup-tail-repair-v3/repair.py --repo "$PWD" --session 2026-10-30 --repair --prevent

Runs 13 repair and 5 writer tests on the VM before mutation. Verifies exact current application source hashes. Fetches historical candles using broker GET with the same User-Agent as the working account reader. A 403 remains a blocker; there is no identity rotation or retry around a permissions error. Never prints provider bodies or credentials.

Accepts only a complete 375-minute / 75-five-minute session and unchanged overlapping OHLC and volume. Keeps original cache bytes in a private audit folder and atomically replaces the cache. Installs only the reviewed operational cache-writer function, backing up its original source. Existing candles are not fabricated or extended. A changed application version blocks installation.

Prevention rejects nonempty incomplete, duplicate, off-grid or current-day writes to the operational warmup cache, checks OHLC, and publishes complete JSON atomically. Other research cache paths retain partial-session support. Empty holiday responses remain empty and do not count as warmup sessions; this is not a holiday calendar certification. No changes to strategy, execution gate or production sealed release.

No services restarted, no controller resume, no orders. Existing Python processes can retain the old writer until reloaded; report running_processes_reloaded=false explicitly. The repaired cache is read on the readiness monitor's normal next validation cycle (typically several minutes). Re-run the market readiness check to confirm warmup. A managed process reload, if required for prevention in existing processes, must use the actual identified service configuration. No claim of active process reload is made by this package.

Broker outages and upstream incomplete responses can still happen; this change prevents accepting those nonempty incomplete sessions at this writer. It cannot guarantee data availability or protect against unrelated programs directly overwriting JSON. If broker values overlap with revisions, repair blocks for review rather than silently altering prior evidence.

Local verification: static syntax, AST scope check and ZIP integrity only. Behavioral tests run on the VM.

## Open-interest-only overlap differences

Retains all prior overlapping normalized candle values including original open interest. Only absent session minutes come from the new broker response. OI differences are recorded privately; null is not converted to zero and no equivalence is asserted. Any overlapping OHLC or volume difference still blocks the repair. A full-session refresh is not performed. The operational NIFTY underlying cache therefore retains its prior OI provenance for existing rows and broker OI for added rows; no OI-based research equivalence is claimed.
