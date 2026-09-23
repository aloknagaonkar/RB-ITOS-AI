# Phase 7D — real-session parity evidence gate (read-only)

This bundle adds a historical capture command and a hash-verified, field-level comparison against the actual live append-only audit. It does **not** claim that September 23 passed: that day's worker was restarted, expiry configuration changed, and old lifecycle data had a missing exact exit minute. Broker historical data alone cannot recreate API publication delay.

## Installation

Add the two files under `backend/market_lab/` and the one test under `tests/` to `feature/pcr-foundation`. Do not modify or truncate any existing `data/live-observation` files. No worker or API restart is needed: both commands are offline CLIs and the UI has not changed.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_hilega_milega_real_session_parity_v1.py tests/test_hilega_milega_phase7c_pending_exit_v1.py -v
```

## Produce a historical functional audit (only if exact Upstox historical data/contract access works)

```bash
python -m market_lab.hilega_milega_phase7d_historical_capture_v1 \
  --session-date 2026-09-23 \
  --expiry 2026-09-29 \
  --output-root data/historical-evidence/hilega-phase7d-2026-09-23
```

This command uses the existing shared live coordinator with a simulated historical clock. It writes a *separate* `step-audit.jsonl`, `detailed-audit-report.json`, and `source-manifest.json`. An `UNAVAILABLE` result is appropriate if the provider cannot return historical unexpired option records or entitlement is missing. It does not call broker order endpoints. For an apples-to-apples option comparison, source timestamps and publication delay must be separately evidenced; otherwise differences are reported, not corrected by fallback.

## Compare to the existing live evidence

```bash
python -m market_lab.hilega_milega_real_session_parity_v1 \
  --session-date 2026-09-23 \
  --historical-audit data/historical-evidence/hilega-phase7d-2026-09-23/step-audit.jsonl \
  --live-audit data/live-observation/hilega-milega-v1/step-audit.jsonl \
  --output data/historical-evidence/hilega-phase7d-2026-09-23/parity-report.json
```

The default result is **INSUFFICIENT_EVIDENCE** for unproven code provenance. Only supply BOTH `--historical-build-id <verified-commit-or-build-id>` and `--live-build-id <verified-commit-or-build-id>` when each is supported by actual capture-time records. The current Git HEAD is *not* evidence for the old live process. September 23 Phase 7C behavior must not be certified by comparing it to old pre-fix live audit records. A new full-session capture from the same build is needed for full parity.

Statuses:
- `PASS`: verified hashes, proven matching build IDs, full event coverage, no mismatch.
- `FAIL`: overlapping events disagree or contradictory duplicated audit records exist.
- `INSUFFICIENT_EVIDENCE`: incomplete coverage, missing option evidence for a recorded entry, unproven/different build IDs, missing files, or invalid audit chain. An invalid chain is a hard audit integrity failure and prohibits comparison, not a successful parity result.

The JSON report includes exact indicators, route decisions, entries/exits, candidate/lifecycle field diffs, coverage gaps, and duplicate conflicts. `0/1/2` CLI exit codes correspond to PASS/FAIL/INSUFFICIENT_EVIDENCE.

### Checklist
- [x] Read-only historical/live comparator with field-level diffs
- [x] Hash chain and build identity preconditions
- [x] Missing-checkpoint and duplicate conflict detection
- [x] Exact option entry/lifecycle semantic comparison
- [x] Historical replay CLI reuses existing shared coordinator
- [x] Historical source manifest with input hashes
- [ ] Capture exact September 23 historical data if broker entitlement permits
- [ ] Verify original September 23 live build and capture completeness (likely insufficient)
- [ ] Run full next-session same-build live-vs-historical acceptance
- [ ] Validate post-Phase7C exact delayed exit in new live session
- [ ] Verify UI expanded audit and correct completed/pending CE P&L
- [ ] Automatic valid expiry resolution (separate future phase)
- [ ] Deferred ATM±2 moneyness research

Safety remains observation-only; five CE strikes are independent hypothetical observations, without quantity or monetary realized P&L.
