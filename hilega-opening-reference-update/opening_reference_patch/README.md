# Opening 09:15 candle reference update

The exact 09:15–09:19 candle closes at09:20. This patch provides its WMA slope reference at that time from the final prior-session completed candle. RSI/EMA/WMA indicator warmup continues as before. Session ownership, setup/crossover comparisons, pending trades and actual position state still reset normally; a separate OpeningReference is used only for confirmation data during09:15–09:19 minute processing. After the first candle, the normal current-session reference takes precedence.

The first slope comparison spans the overnight gap and is identified in audit fields reference_crosses_session and reference_bar_timestamp. Bootstrap also identifies opening_reference_timestamp. No fallback is created from incomplete/unready, nonfinite, target-session or future-session warmup snapshots. No orders, risk, cutoff, waiting, RSI thresholds, setup detection or confirmation/persistence requirements are changed.

Targets: backend/market_lab/hilega_alignment_dual_exit_live_v1.py and hilega_v2_alignment_replay_v1.py; new helper hilega_opening_reference_v1.py. The legacy non-alignment adapter is outside this patch. Historical auto-cache signatures include the helper so old cached research results are recomputed.

## Install

From the actual RB-ITOS-AI repository root, put the archive there and extract it:

```bash
tar -xzf hilega-opening-reference-update.tar.gz
source .venv/bin/activate
python opening_reference_patch/install_opening_reference.py --check
python opening_reference_patch/install_opening_reference.py
PYTHONPATH=backend python opening_reference_patch/test_hilega_opening_reference_v1.py
bash scripts/restart.sh
```

The installer validates all unique source anchors and compiles every result before writing. It aborts without edits if the current source structure is incompatible. It backs up affected current files under backups/opening-reference-TIMESTAMP, then applies each prepared file atomically. Reapplying is supported. It edits the current modules in place rather than replacing them with the older source snapshot. It does not restart processes by itself.

If using another Python launcher, use that repository's existing virtualenv interpreter. Existing test invocation with optional dependencies installed: PYTHONPATH=backend python -m unittest discover -s tests -p test_hilega_alignment_dual_exit_live_v1.py. Six focused live tests can alternatively be run via PYTHONPATH=backend python opening_reference_patch/run_live_checks.py, excluding the unrelated bridge test. Optional reproduction using existing locally available candle cache: PYTHONPATH=backend python opening_reference_patch/validate_oct8_live_parity.py data/historical-evidence/hilega-milega-underlying-cache-v1.

## Validation

- Eight reference helper tests passed.
- Six existing focused live adapter tests passed. The complete test module import required unavailable optional python-dotenv for an unrelated sandbox bridge; that bridge test was not run.
- Live adapter and historical replay agree on the opening strength and reference timestamp.
- Oct8 first completed candle at09:20: previous WMA50.243908 (Oct7 15:25), current WMA48.449218, bearish strength1.794691.
- Original canonical crossover comparison has no previous-session RSI reference.
- Full Oct8 replay remains -58.80; all six trade directions, entry/exit timestamps, prices and points are unchanged.
- With existing entry rules, Oct8 bearish entry remains09:22. A09:20 entry requires a separate change to signal-boundary confirmation/persistence and is not implemented here.
- Installer reapply validation passed.

Prepared and applied to the recovered local source snapshot only. Remote VM deployment was not performed. All validation artifacts are included; opening-reference.patch is available for review.
