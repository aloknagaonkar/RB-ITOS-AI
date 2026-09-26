# Hilega + OI/PCR Temporal Sequence Research v1

This is the next research phase after the 180-session walk-forward showed that no simple 5m/10m/15m OI MATCH filter survived the conservative train criteria.

## Purpose

Instead of asking only:

```text
Does OI MATCH the Hilega direction at 5 minutes?
```

this study asks:

```text
What happened across 15m -> 10m -> 5m before the Hilega entry?
```

Examples:

```text
BUILD -> BUILD -> BULLISH
BEARISH -> UNWIND -> BULLISH
BULLISH -> BULLISH -> BULLISH
AMBIGUOUS relation -> MATCH -> MATCH
```

## Exact market-data method

The script keeps the same methodology used in the previous research:

- moving ATM at Hilega signal time `T`
- expiry-aware panel:
  - Monday ±3
  - Tuesday ±2
  - Wednesday ±5
  - Thursday ±5
  - Friday ±4
- compare the **same physical signal-time strikes** at:
  - T vs T-5
  - T vs T-10
  - T vs T-15
- no interpolation
- no nearest-strike substitution
- no synthetic OI
- missing physical strike => that horizon is unavailable

OI state:

```text
CE ΔOI < 0, PE ΔOI > 0 => BULLISH
CE ΔOI > 0, PE ΔOI < 0 => BEARISH
CE ΔOI > 0, PE ΔOI > 0 => BUILD
CE ΔOI < 0, PE ΔOI < 0 => UNWIND
```

## Outputs

For all 180 sessions:

- detailed trade-level temporal features
- 15m -> 10m -> 5m OI state sequence
- 15m -> 10m -> 5m MATCH/OPPOSITE/AMBIGUOUS sequence
- PCR trend across horizons
- bullish/bearish breakdown
- Hilega Route A/B/opening breakdown
- minimum-n sequence ranking using capped ±20 points, median, win rate, and raw points

## Install

Copy:

```text
hilega_oi_temporal_sequence_research.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

## Run

Since the 180 replay files should already exist after the previous run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_oi_temporal_sequence_research.py \
  --skip-replay \
  | tee /tmp/hilega-oi-temporal-sequence.txt
```

If replay is missing for any date:

```bash
python scripts/hilega_oi_temporal_sequence_research.py \
  --run-replay \
  | tee /tmp/hilega-oi-temporal-sequence.txt
```

## Output directory

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
temporal-sequence-v1/
```

Files:

- `hilega-180-temporal-sequence-features-v1.csv`
- `hilega-180-temporal-sequence-summary-v1.csv`
- `hilega-180-temporal-sequence-report-v1.txt`
- `historical-replay-build-v1.log` when replay is rebuilt

Research only. Hilega logic and execution settings are unchanged.
