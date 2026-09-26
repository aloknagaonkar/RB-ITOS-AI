# Hilega 60-session + 18 bullish + 18 bearish validation

This package validates the previously discovered candidate **without retuning it**.

Frozen candidate:

```text
OI relation = MATCH
3.0% <= SUMABS < 5.0%
exclude 13:00–13:59
```

The analysis includes:

- latest 60 sessions with real per-strike historical OI
- Hilega historical replay for those sessions
- exact same-physical-strike T vs T-5 moving-ATM calculation
- Model C widths:
  - Monday ±3
  - Tuesday ±2
  - Wednesday ±5
  - Thursday ±5
  - Friday ±4
- bullish-only and bearish-only candidate performance
- dominant-leg breakdown
- frozen 18 bullish directional sessions
- frozen 18 bearish directional sessions
- leave-one-session-out checks
- remove-best-winner check
- median points
- capped ±20-point total

The script does **not** modify Hilega logic and does not enable execution.

## Install

Copy:

```text
hilega_60_session_directional_validation.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

## First run: build all required historical replay + analyze

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_60_session_directional_validation.py \
  --run-replay \
  | tee /tmp/hilega-60-directional-validation.txt
```

The replay CLI's large JSON output is captured into a file rather than dumped to the terminal.

## Later analysis-only runs

```bash
python scripts/hilega_60_session_directional_validation.py \
  --skip-replay \
  | tee /tmp/hilega-60-directional-validation.txt
```

## Outputs

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
60-session-directional-validation-v1/
```

Files:

- `hilega-60-session-model-c-joined-v1.csv`
- `hilega-directional-36-model-c-joined-v1.csv`
- `hilega-60-session-directional-validation-summary-v1.txt`
- `historical-replay-build-v1.log` when `--run-replay` is used

## Frozen directional sets

The script contains the exact 18 bullish and exact 18 bearish session dates supplied for this validation. They are kept separate from the main 60-session result.
