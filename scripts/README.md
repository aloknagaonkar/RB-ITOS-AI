# Hilega + PCR/OI 180-session chronological walk-forward

This package implements the next research phase using all 180 real-OI sessions already discovered in the repository.

## Important methodological note

The split is chronological:

```text
oldest 60  -> TRAIN
middle 60  -> VALIDATION
newest 60  -> EVALUATION
```

However, the newest sessions have already been inspected in earlier research. Therefore the newest 60 are a **retrospective evaluation**, not a pristine never-seen holdout.

A future/live forward sample is still required before any OI rule is considered for production.

## Features

For every Hilega entry the script calculates, using the signal-time moving ATM and exact same physical strikes:

- 5-minute CE/PE OI delta and percentage
- 10-minute CE/PE OI delta and percentage
- 15-minute CE/PE OI delta and percentage
- 5m/10m/15m PCR before/current/change
- 5m/10m/15m OI state
- 5m/10m/15m MATCH / OPPOSITE / AMBIGUOUS relation
- 5m dominant OI leg
- Hilega direction
- Hilega route
- time bucket
- weekday
- actual days to expiry
- outcome points

No nearest-strike substitution or interpolation is performed.

## Train-only candidate discovery

The search family is intentionally limited and declared in the script before validation:

- 5m relation must be MATCH
- broad 5m intensity bands:
  - any
  - 0-2%
  - 2-3%
  - 3-5%
  - 5-8%
- direction:
  - any
  - bullish
  - bearish
- time:
  - all
  - exclude 13:00-13:59
- 10m:
  - any
  - MATCH
  - not OPPOSITE
- 15m:
  - any
  - MATCH
  - not OPPOSITE

Minimum TRAIN sample size is 15.

The script ranks only TRAIN candidates. A maximum of 10 TRAIN-eligible candidates are carried to VALIDATION. Only validation survivors are reported on EVALUATION.

The previously discovered `MATCH + 3-5% + exclude 13h` candidate is reported separately as a **contaminated benchmark** and is not treated as clean train discovery.

## Install

Copy:

```text
hilega_180_walkforward_research.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

## First run

This may take time because it builds Hilega replay across all 180 dates:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_180_walkforward_research.py \
  --run-replay \
  | tee /tmp/hilega-180-walkforward.txt
```

The large replay CLI JSON is captured in:

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
180-session-walkforward-v1/
historical-replay-build-v1.log
```

## Later reruns

```bash
python scripts/hilega_180_walkforward_research.py \
  --skip-replay \
  | tee /tmp/hilega-180-walkforward.txt
```

## Outputs

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
180-session-walkforward-v1/
```

Outputs:

- `hilega-180-session-features-v1.csv`
- `train-oldest-60-v1.csv`
- `validation-middle-60-v1.csv`
- `evaluation-newest-60-v1.csv`
- `train-discovered-candidates-v1.csv`
- `walkforward-summary-v1.txt`
- `historical-replay-build-v1.log`

Research only. No Hilega logic or execution settings are modified.
