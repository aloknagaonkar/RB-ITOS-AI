#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

EXPANSION_DATES=(
  2026-06-02
  2026-06-12
  2026-06-16
  2026-06-17
  2026-06-18
  2026-06-24
  2026-06-01
  2026-06-23
  2026-06-29
  2026-07-07
  2026-07-08
  2026-07-14
)

BASE_DATES=(
  2026-05-12
  2026-05-18
  2026-08-25
  2026-05-20
  2026-05-25
  2026-05-19
  2026-05-29
)

echo "== 1. Generate unchanged V1.1 audits for expansion dates =="
for d in "${EXPANSION_DATES[@]}"; do
  python -m market_lab.oi_price_regime_transition_audit_v1_1 \
    --session-date "$d" \
    --moving-wings 5 \
    --csv "data/historical-evidence/oi-price-regime-audit-${d}-v1-1.csv" \
    --json-output "data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json"
done

echo "== 2. Build frozen Change-PCR rows across all 19 dates =="

ARGS=()
for d in "${BASE_DATES[@]}" "${EXPANSION_DATES[@]}"; do
  ARGS+=(--audit-json "data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json")
done

python -m market_lab.change_pcr_validation_v1 \
  "${ARGS[@]}" \
  --rows-csv data/historical-evidence/change-pcr-validation-rows-v1-19sessions.csv \
  --summary-json data/historical-evidence/change-pcr-validation-summary-v1-19sessions.json

echo "== 3. Run unchanged persistent deterioration / propagation study =="

python -m market_lab.change_pcr_persistent_deterioration_v1 \
  --rows-csv data/historical-evidence/change-pcr-validation-rows-v1-19sessions.csv \
  --candidates-csv data/historical-evidence/change-pcr-persistent-deterioration-candidates-v1-19sessions.csv \
  --summary-json data/historical-evidence/change-pcr-persistent-deterioration-summary-v1-19sessions.json

echo "== 4. Compare original 7 vs frozen expansion 12 vs combined 19 =="

python -m market_lab.change_pcr_propagation_expansion_v1 \
  --candidates-csv data/historical-evidence/change-pcr-persistent-deterioration-candidates-v1-19sessions.csv \
  --summary-json data/historical-evidence/change-pcr-propagation-expansion-summary-v1-19sessions.json

echo "DONE"
