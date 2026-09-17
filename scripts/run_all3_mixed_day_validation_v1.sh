#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

MIXED_DATES=(
  2026-05-04 2026-05-05 2026-05-06 2026-05-07 2026-05-08 2026-05-11
  2026-05-13 2026-05-14 2026-05-15 2026-05-21 2026-05-22 2026-05-26
  2026-05-27 2026-06-03 2026-06-04 2026-06-05 2026-06-08 2026-06-09
)

BULLISH_DATES=(
  2026-05-18 2026-05-20 2026-05-25 2026-06-02
  2026-06-12 2026-06-16 2026-06-17 2026-06-18
  2026-06-24 2026-07-06 2026-07-10 2026-07-13
  2026-07-17 2026-07-27 2026-07-29 2026-08-03
  2026-08-25 2026-09-02
)

BEARISH_DATES=(
  2026-05-12 2026-05-19 2026-05-29 2026-06-01
  2026-06-23 2026-06-29 2026-07-07 2026-07-08
  2026-07-14 2026-07-16 2026-07-22 2026-08-18
  2026-08-24 2026-08-26 2026-08-27 2026-09-03
  2026-09-07 2026-09-08
)

ALL_DATES=("${BULLISH_DATES[@]}" "${BEARISH_DATES[@]}" "${MIXED_DATES[@]}")

echo "== 1. Generate unchanged V1.1 audits for mixed cohort =="
for d in "${MIXED_DATES[@]}"; do
  python -m market_lab.oi_price_regime_transition_audit_v1_1 \
    --session-date "$d" \
    --moving-wings 5 \
    --csv "data/historical-evidence/oi-price-regime-audit-${d}-v1-1.csv" \
    --json-output "data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json"
done

echo "== 2. Build unchanged 5m/10m/15m horizon-state rows across all 54 sessions =="
ARGS=()
for d in "${ALL_DATES[@]}"; do
  ARGS+=(--audit-json "data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json")
done

python -m market_lab.change_pcr_validation_v1 \
  "${ARGS[@]}" \
  --rows-csv data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv \
  --summary-json data/historical-evidence/change-pcr-validation-summary-v1-54sessions.json

echo "== 3. Run unchanged ALL_3 persistence/day-type validation with frozen mixed labels =="
python -m market_lab.all3_persistence_daytype_validation_v1 \
  --rows-csv data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv \
  --labels-csv data/historical-evidence/all3-mixed-reversal-labels-v1.csv \
  --sessions-csv data/historical-evidence/all3-persistence-daytype-sessions-v1-54sessions.csv \
  --summary-json data/historical-evidence/all3-persistence-daytype-summary-v1-54sessions.json

echo "DONE"
