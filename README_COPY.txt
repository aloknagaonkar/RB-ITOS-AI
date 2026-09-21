CONTROL FAILURE HISTORICAL V5
=============================

Research-only historical validation of the two-candle control-failure hypothesis.

Copy into ~/RB-ITOS-AI preserving folders:

scripts/analyze_control_failure_historical_v5.py
tests/test_analyze_control_failure_historical_v5.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_analyze_control_failure_historical_v5.py -v

Check available historical sessions
-----------------------------------
find data/historical-evidence/historical-oi-build -mindepth 2 -maxdepth 2 -name positioning.json -printf '%h\n' | sort

Run last 5 available sessions first
-----------------------------------
python scripts/analyze_control_failure_historical_v5.py \
  --last-n 5 \
  --wings 2 \
  --output-dir data/historical-evidence/control-failure-v5-last5

Then expand to last 20 sessions
-------------------------------
python scripts/analyze_control_failure_historical_v5.py \
  --last-n 20 \
  --wings 2 \
  --output-dir data/historical-evidence/control-failure-v5-last20

Or explicit dates
-----------------
python scripts/analyze_control_failure_historical_v5.py \
  --dates 2026-09-18 2026-09-17 2026-09-16 \
  --wings 2 \
  --output-dir data/historical-evidence/control-failure-v5-selected

Method
------
- Exact 5-minute checkpoints.
- Moving ATM +/-2 at each checkpoint.
- Same exact physical strikes are compared between T and T-5.
- No nearest strike.
- No nearest timestamp.
- No interpolation.
- Missing required exact strike/OI fails that session clearly.
- Detects bullish and bearish mirror patterns.
- A control-failure candidate requires BOTH within a two-candle window:
    * directional OI pressure decay
    * failed price response against that OI direction
- Valid component orders:
    DECAY_THEN_FAILURE
    FAILURE_THEN_DECAY
    SAME_CANDLE
- Measures directional forward movement at +5/+10/+15/+30m.
- Measures 30m close-based MFE/MAE.
- Measures minutes until ATM and 2/5 or 4/5 breadth confirmation.
- Research only; no strategy or execution changes.

Outputs
-------
control-failure-candles-v5.csv
control-failure-events-v5.csv
control-failure-summary-v5.json
