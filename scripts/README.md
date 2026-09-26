# Hilega + OI/PCR True Interval Sequence Research v2

This package corrects an important issue in Temporal Sequence Research v1.

## What was wrong with v1?

V1 displayed sequences such as:

```text
15m -> 10m -> 5m
```

but those states actually represented cumulative comparisons:

```text
T vs T-15
T vs T-10
T vs T-5
```

Those are useful multi-horizon features, but they are **not true chronological interval transitions**.

The v1 PCR trend had the same issue: `h15_pcr_current`, `h10_pcr_current`, and `h5_pcr_current` all represented PCR at the same signal-time snapshot `T`, which explains why the report showed every trade as `MIXED`.

## What v2 computes

Using the same signal-time moving-ATM physical strike panel:

```text
Interval 1: T-15 -> T-10
Interval 2: T-10 -> T-5
Interval 3: T-5  -> T
```

The exact same physical strikes must exist at all four snapshots.

PCR is calculated separately at:

```text
T-15
T-10
T-5
T
```

and classified as:

```text
STEADY_RISE
STEADY_FALL
MOSTLY_RISING
MOSTLY_FALLING
MIXED
```

## Run

The 180 Hilega replays already exist, so use:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/hilega_oi_true_interval_sequence_research.py \
  --skip-replay \
  | tee /tmp/hilega-oi-true-interval-sequence.txt
```

## Outputs

```text
data/historical-evidence/hilega-pcr-oi-support-research-v1/
true-interval-sequence-v2/
```

Files:

- `hilega-180-true-interval-sequence-features-v2.csv`
- `hilega-180-true-interval-sequence-summary-v2.csv`
- `hilega-180-true-interval-sequence-report-v2.txt`

Research only. Hilega logic and execution settings are unchanged.
