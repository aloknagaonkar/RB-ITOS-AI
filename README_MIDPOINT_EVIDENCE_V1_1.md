# Midpoint Evidence V1.1 patch

Copy this ZIP into the root of `RB-ITOS-AI`, overwriting the existing files.

Files replaced:

```text
backend/market_lab/opening_red_midpoint_evidence_v1.py
tests/test_opening_red_midpoint_evidence_v1.py
docs/OPENING_RED_MIDPOINT_EVIDENCE_V1_1.md
```

The already generated `underlying-ohlc-*.csv` files do not need to be rebuilt.
V1.1 changes only research feature extraction/diagnostics.

Run:

```bash
python -m pytest \
  tests/test_historical_underlying_ohlc_sidecar.py \
  tests/test_opening_red_midpoint_evidence_v1.py -v
```

Then rerun the same 100-session `opening_red_midpoint_evidence_v1` command,
preferably writing to new V1.1 output filenames.
