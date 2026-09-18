#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

pytest -q tests/test_post_confirmation_price_impulse_validation_v1.py

ROWS="data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv"
OUTDIR="data/historical-evidence/post-confirmation-price-impulse-v1"
mkdir -p "$OUTDIR"

mapfile -t DATES < <(
python - <<'PY'
import csv
p="data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv"
with open(p,newline="") as f:
    print("\n".join(sorted({r["session_date"] for r in csv.DictReader(f)})))
PY
)

if [[ "${#DATES[@]}" -ne 54 ]]; then
  echo "Expected 54 development sessions, got ${#DATES[@]}" >&2
  exit 1
fi

ARGS=()
for d in "${DATES[@]}"; do
  f="data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json"
  [[ -f "$f" ]] || { echo "Missing development audit: $f" >&2; exit 1; }
  ARGS+=(--audit-json "$f")
done

printf '%s\n' "${DATES[@]}" > "$OUTDIR/development-dates-54-frozen.txt"

python -m market_lab.post_confirmation_price_impulse_validation_v1 \
  --rows-csv "$ROWS" \
  "${ARGS[@]}" \
  --events-csv "$OUTDIR/post-confirmation-price-impulse-v1-events-54sessions.csv" \
  --summary-json "$OUTDIR/post-confirmation-price-impulse-v1-summary-54sessions.json"
