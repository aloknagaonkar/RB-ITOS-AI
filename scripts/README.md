# Hilega 30-session OI research

## Copy to repo

Extract the zip, then copy `hilega_oi_30_session_research.py` into the repo root:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
```

## Run

```bash
python hilega_oi_30_session_research.py
```

## Optional: save terminal output

```bash
python hilega_oi_30_session_research.py | tee /tmp/hilega-oi-30-session.txt
```

## Result CSV

The script writes:

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/hilega-moving-atm-expiry-width-30-session-v1.csv
```

## Research models

- MODEL_A_FIXED_5: ATM ±5 every day
- MODEL_C_EXPIRY_AWARE:
  - Monday ±3
  - Tuesday ±2
  - Wednesday ±5
  - Thursday ±5
  - Friday ±4

The script uses moving ATM at signal time T and the same exact physical strikes at T and T-5 minutes.

It does not enable execution, paper orders, or option selection.
