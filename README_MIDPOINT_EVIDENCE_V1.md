# Midpoint Evidence V1 bundle

Copy the contents of this ZIP into the **root of `RB-ITOS-AI`**. The ZIP already
contains the repository-relative directories:

```text
backend/market_lab/
tests/
docs/
```

## Files

- `backend/market_lab/historical_underlying_ohlc_sidecar.py`
- `backend/market_lab/opening_red_midpoint_evidence_v1.py`
- `tests/test_historical_underlying_ohlc_sidecar.py`
- `tests/test_opening_red_midpoint_evidence_v1.py`
- `docs/OPENING_RED_MIDPOINT_EVIDENCE_V1.md`

## First test

```bash
python -m pytest \
  tests/test_historical_underlying_ohlc_sidecar.py \
  tests/test_opening_red_midpoint_evidence_v1.py -v
```

## Then

Build one underlying 1-minute OHLC CSV per development block using the existing
historical manifests and the sidecar CLI.

Example shape:

```bash
python -m market_lab.historical_underlying_ohlc_sidecar \
  --underlying "NSE_INDEX|Nifty 50" \
  --manifest <TRAIN_MANIFEST.json> \
  --output data/historical-evidence/underlying-ohlc-train.json \
  --csv-output data/historical-evidence/underlying-ohlc-train.csv
```

Repeat for TRAIN, OOS-A, OOS-B, OOS-C and OOS-D.

Then run:

```bash
python -m market_lab.opening_red_midpoint_evidence_v1 \
  --block 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv|data/historical-evidence/evidence-20.csv|data/historical-evidence/positioning-train.csv' \
  --block 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv|data/historical-evidence/evidence-oos.csv|data/historical-evidence/positioning-oos-a.csv' \
  --block 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv|data/historical-evidence/evidence-oos-b.csv|data/historical-evidence/positioning-oos-b.csv' \
  --block 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv|data/historical-evidence/evidence-oos-c.csv|data/historical-evidence/positioning-oos-c.csv' \
  --block 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv|data/historical-evidence/evidence-oos-d.csv|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/opening-red-midpoint-evidence-v1-development.json \
  --csv-output data/historical-evidence/opening-red-midpoint-evidence-v1-development.csv
```

Do not run E/F/G/H in this phase.

The actual manifest filenames may differ in your repository. After the tests pass,
list them with:

```bash
ls -1 data/historical-validation/*.json
```

and use the existing TRAIN/A/B/C/D manifests.
