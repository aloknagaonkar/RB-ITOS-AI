# Midpoint Primary Continuation Option Backtest V1

Copy this bundle into the root of `RB-ITOS-AI`.

Files:

```text
backend/market_lab/midpoint_primary_continuation_option_backtest_v1.py
tests/test_midpoint_primary_continuation_option_backtest_v1.py
docs/MIDPOINT_PRIMARY_CONTINUATION_OPTION_BACKTEST_V1.md
README_MIDPOINT_PRIMARY_CONTINUATION_OPTION_BACKTEST_V1.md
```

Tests:

```bash
python -m pytest \
  tests/test_midpoint_primary_continuation_option_backtest_v1.py -v
```

The run command requires the five existing positioning CSVs and the five
existing option-OHLC sidecar CSVs.

Use `ls` first to confirm exact option-OHLC filenames before running the
backtest.
