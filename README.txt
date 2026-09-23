PHASE 7D.3 — IMMUTABLE MARKET-DATA EVIDENCE (OPT-IN)
===================================================

Single ZIP package for the exact Phase 7D.1 + 7D.2 VM code hashes.
DO NOT forcibly overwrite CONFLICT files. Existing strategy logic untouched.

INSTALL (unzip into ~/phase7d3-patch or work from this package directory):
  python apply_phase7d3.py --repo ~/RB-ITOS-AI
  python apply_phase7d3.py --repo ~/RB-ITOS-AI --apply   # only if no conflicts

TEST:
  cd ~/RB-ITOS-AI && source .venv/bin/activate
  PYTHONPATH=backend python -m pytest -q \
    tests/test_hilega_phase7d3_market_evidence_v1.py \
    tests/test_hilega_phase7d2_cutoff_order_v1.py \
    tests/test_hilega_phase7d1_acquisition_v1.py \
    tests/test_hilega_milega_live_shadow_v1.py

WHAT CHANGES
* New shared source wrapper records the actual response as seen at every live
  source invocation (underlying 1m, each requested option 1m, exact-expiry
  contracts, including empty responses, and warmup market data consumed).
* Each source response has a UTC acquisition timestamp; journal records are
  sequential and hash chained. Duplicate returned snapshots use a response hash
  reference so 5-second polling does not repeatedly store identical candles.
* Fails closed on missing/changed evidence, duplicate writers, changed call
  order, missing data, or mismatched strategy/coordinator source hashes.
* Source journal never records the Upstox token. Journal files are private
  (new files mode 0600). Preserve/acquire backups on secured storage.
* Added offline source-tape replay CLI. No broker/API calls in replay.
* Historical capture optional --record-input-evidence writes exact underlying
  and option responses consumed by historical capture to separate JSON files,
  hashes them in source-manifest.json, and refuses to overwrite raw files.

LIVE CAPTURE IS OFF BY DEFAULT
  Add to the VM app's .env (only for Hilega shadow):
     HILEGA_MARKET_EVIDENCE_ENABLED=1
     HILEGA_MARKET_EVIDENCE_ROOT=data/live-observation/hilega-market-evidence-v1
  Then restart ONLY your existing live-shadow service, at an appropriate time,
  using your existing service manager. DO NOT run a second competing worker.
  The installer does not restart any service. Do not enable order execution.
  Verify new dated evidence journal exists and is growing, with permissions 600.
  Worker rotates journal by IST session date and appends process-start identity
  at each process restart. Reboots are replayed as distinct process segments.

VERIFY A FINISHED JOURNAL (example date):
  cd ~/RB-ITOS-AI && source .venv/bin/activate
  PYTHONPATH=backend python - <<'PYVERIFY'
  from market_lab.hilega_market_evidence_v1 import verify_journal
  from pathlib import Path
  p=Path('data/live-observation/hilega-market-evidence-v1/2026-09-24.jsonl')
  r=verify_journal(p)
  print('VERIFIED',len(r),'events', 'source_calls',sum(x['kind'] in
        ('warmup','underlying','option','contracts') for x in r))
  PYVERIFY

STRICT OFFLINE REPLAY (ONLY AFTER A REAL RECORDED SESSION):
  PYTHONPATH=backend python -m market_lab.hilega_market_evidence_replay_v1 \
    --journal data/live-observation/hilega-market-evidence-v1/2026-09-24.jsonl \
    --expiry YYYY-MM-DD \
    --output-root data/historical-evidence/hilega-source-replay-2026-09-24-d1
  Replace sample day and expiry with your actual recorded values. Run with
  the exact recorded strategy/coordinator source hashes: a later code update
  intentionally FAILS rather than claiming reproducible parity.

OPTIONAL NEW HISTORICAL RETRIEVAL SNAPSHOT:
  PYTHONPATH=backend python -m market_lab.hilega_milega_phase7d_historical_capture_v1 \
    --session-date YYYY-MM-DD --expiry YYYY-MM-DD \
    --output-root data/historical-evidence/new-fresh-directory \
    --record-input-evidence

EVIDENCE LIMITATIONS
* These journals begin only AFTER opt-in capture is enabled; they CANNOT recover
  missing original 2026-09-23 live 1-minute responses retroactively.
* Hash chaining detects changes and duplicate/reordered calls but is not a
  WORM/external notarization guarantee. Back up and protect files separately.
* The tape contains exactly responses REQUESTED by the current coordinator.
  It does not proactively capture all five CE quotes every minute without a
  request. Pre-entry five-strike market snapshots are recorded when queried.
* Do not claim full historical/live option parity until complete lifecycle
  event coverage and the same source/build preconditions are verified.
* No strategy rule changes, new orders, paper orders, trading activation,
  synthetic candle filling, or original-audit rewrites.

LOCAL VERIFICATION
  62 targeted tests passed on assembled Phase 7D.2 baseline.
  Full offline suite: 1,148 passed / 13 previously known failures.
  VM validation and live opt-in capture remain pending.
