#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

pytest -q tests/test_structure_price_lag_exact_option_replay_v1.py

OUTDIR="data/historical-evidence/structure-price-lag-exact-option-replay-v1"
mkdir -p "$OUTDIR"

declare -A MANIFESTS=(
  [OOS_E]="data/historical-validation/manifest-oos-e-20.json"
  [OOS_F]="data/historical-validation/manifest-oos-f-20.json"
  [OOS_G]="data/historical-validation/manifest-oos-g-20.json"
  [OOS_H]="data/historical-validation/manifest-oos-h-20.json"
)

declare -A CACHE=(
  [OOS_E]="data/historical-option-ohlc-cache-oos-e"
  [OOS_F]="data/historical-option-ohlc-cache-oos-f"
  [OOS_G]="data/historical-option-ohlc-cache-oos-g"
  [OOS_H]="data/historical-option-ohlc-cache-oos-h"
)

declare -A OHLC=(
  [OOS_E]="data/historical-evidence/option-ohlc-oos-e.csv"
  [OOS_F]="data/historical-evidence/option-ohlc-oos-f.csv"
  [OOS_G]="data/historical-evidence/option-ohlc-oos-g.csv"
  [OOS_H]="data/historical-evidence/option-ohlc-oos-h.csv"
)

declare -A POSITIONING=(
  [OOS_E]="data/historical-evidence/positioning-oos-e.csv"
  [OOS_F]="data/historical-evidence/positioning-oos-f.csv"
  [OOS_G]="data/historical-evidence/positioning-oos-g.csv"
  [OOS_H]="data/historical-evidence/positioning-oos-h.csv"
)

# Generate missing exact option OHLC blocks from existing historical sidecar.
for block in OOS_E OOS_F OOS_G OOS_H; do
  if [[ -f "${OHLC[$block]}" ]]; then
    echo "OHLC EXISTS $block -> ${OHLC[$block]}"
  else
    echo "GENERATE OHLC $block"
    set -a
    source .env
    set +a
    lower=$(echo "$block" | tr '[:upper:]_' '[:lower:]-')
    python -m market_lab.historical_option_ohlc_sidecar \
      --underlying "NSE_INDEX|Nifty 50" \
      --manifest "${MANIFESTS[$block]}" \
      --wings 5 \
      --cache-dir "${CACHE[$block]}" \
      --output "data/historical-evidence/option-ohlc-${lower}.json" \
      --csv-output "${OHLC[$block]}"
  fi

  [[ -f "${POSITIONING[$block]}" ]] || {
    echo "Missing positioning evidence: ${POSITIONING[$block]}" >&2
    exit 1
  }
done

EVENTS="data/historical-evidence/structure-price-lag-remaining-move-v1/structure-price-lag-remaining-move-v1-events-80sessions.csv"
[[ -f "$EVENTS" ]] || { echo "Missing events file: $EVENTS" >&2; exit 1; }

python -m market_lab.structure_price_lag_exact_option_replay_v1 \
  --events "$EVENTS" \
  --manifest "OOS_E|${MANIFESTS[OOS_E]}" \
  --manifest "OOS_F|${MANIFESTS[OOS_F]}" \
  --manifest "OOS_G|${MANIFESTS[OOS_G]}" \
  --manifest "OOS_H|${MANIFESTS[OOS_H]}" \
  --positioning "OOS_E|${POSITIONING[OOS_E]}" \
  --positioning "OOS_F|${POSITIONING[OOS_F]}" \
  --positioning "OOS_G|${POSITIONING[OOS_G]}" \
  --positioning "OOS_H|${POSITIONING[OOS_H]}" \
  --option-ohlc "OOS_E|${OHLC[OOS_E]}" \
  --option-ohlc "OOS_F|${OHLC[OOS_F]}" \
  --option-ohlc "OOS_G|${OHLC[OOS_G]}" \
  --option-ohlc "OOS_H|${OHLC[OOS_H]}" \
  --trades-csv "$OUTDIR/structure-price-lag-exact-option-replay-v1-trades-80sessions.csv" \
  --summary-json "$OUTDIR/structure-price-lag-exact-option-replay-v1-summary-80sessions.json"
