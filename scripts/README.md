# Hilega Model C MATCH failure analysis

This script analyzes the existing 30-session research CSV and asks:

> When OI matches Hilega direction, what distinguishes winners from losers?

It does not change strategy logic and does not enable execution.

## Install

Copy `hilega_match_failure_analysis.py` into:

```text
~/RB-ITOS-AI/scripts/
```

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_match_failure_analysis.py \
  | tee /tmp/hilega-match-failure-analysis.txt
```

## Required input

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
hilega-moving-atm-expiry-width-30-session-v1.csv
```

## Outputs

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
match-failure-analysis-v1/
```

Files:
- `model-c-match-winner-loser-features-v1.csv`
- `model-c-match-winner-loser-summary-v1.txt`

The analysis covers:
- direction
- Hilega entry route
- time of day
- weekday
- days to expiry
- OI intensity
- PCR level
- absolute PCR change
- dominant OI leg
- winner/loss numeric comparisons
- descriptive two-feature slices
- per-session concentration

All results are descriptive research only.
