# Hilega MATCH robustness analysis

This is the next step after the 30-session winner-vs-loser analysis.

It does **not** search hundreds of combinations. It deliberately tests only a small set of broad candidate slices found in the prior analysis and checks whether they survive basic robustness tests.

## Copy

Copy:

```text
hilega_match_robustness_analysis.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_match_robustness_analysis.py \
  | tee /tmp/hilega-match-robustness.txt
```

## Input

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
match-failure-analysis-v1/
model-c-match-winner-loser-features-v1.csv
```

## What it checks

- baseline MATCH
- exclusion of 13:00–13:59
- intensity 3–5%
- exclusion of CE_BUILD-dominant matches
- PCR-level 1.10–1.29
- absolute PCR change 0.02–0.04
- two limited combined slices

For each candidate it reports:

- sample size
- win rate
- average and median points
- total points
- points capped at ±20 to reduce outlier influence
- result after removing the single best winner
- leave-one-session-out robustness

No production rule is frozen by this script.
