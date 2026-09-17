#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

pytest -q tests/test_structure_price_lag_option_exit_validation_v1.py

TRADES="data/historical-evidence/structure-price-lag-exact-option-replay-v1/structure-price-lag-exact-option-replay-v1-trades-80sessions.csv"
OUTDIR="data/historical-evidence/structure-price-lag-option-exit-validation-v1"

[[ -f "$TRADES" ]] || {
  echo "Missing exact-option replay trades: $TRADES" >&2
  exit 1
}

mkdir -p "$OUTDIR"

for f in \
  data/historical-evidence/option-ohlc-oos-e.csv \
  data/historical-evidence/option-ohlc-oos-f.csv \
  data/historical-evidence/option-ohlc-oos-g.csv \
  data/historical-evidence/option-ohlc-oos-h.csv
do
  [[ -f "$f" ]] || { echo "Missing option OHLC: $f" >&2; exit 1; }
done

python -m market_lab.structure_price_lag_option_exit_validation_v1 \
  --trades "$TRADES" \
  --option-ohlc 'OOS_E|data/historical-evidence/option-ohlc-oos-e.csv' \
  --option-ohlc 'OOS_F|data/historical-evidence/option-ohlc-oos-f.csv' \
  --option-ohlc 'OOS_G|data/historical-evidence/option-ohlc-oos-g.csv' \
  --option-ohlc 'OOS_H|data/historical-evidence/option-ohlc-oos-h.csv' \
  --results-csv "$OUTDIR/structure-price-lag-option-exit-validation-v1-results-80sessions.csv" \
  --summary-json "$OUTDIR/structure-price-lag-option-exit-validation-v1-summary-80sessions.json"
