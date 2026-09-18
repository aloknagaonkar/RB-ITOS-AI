#!/usr/bin/env bash
set -euo pipefail
cd ~/RB-ITOS-AI
source .venv/bin/activate

pytest -q tests/test_early_persistence_asymmetry_validation_v1.py

mapfile -t DATES < <(
python - <<'PY'
import csv
p="data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv"
with open(p,newline="") as f:
    print("\n".join(sorted({r["session_date"] for r in csv.DictReader(f)})))
PY
)

ARGS=()
for d in "${DATES[@]}"; do
  f="data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json"
  [[ -f "$f" ]] || { echo "Missing: $f" >&2; exit 1; }
  ARGS+=(--audit-json "$f")
done

python -m market_lab.early_persistence_asymmetry_validation_v1 \
  --rows-csv data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv \
  "${ARGS[@]}" \
  --snapshots-csv data/historical-evidence/early-persistence-asymmetry-snapshots-v1-54sessions.csv \
  --summary-json data/historical-evidence/early-persistence-asymmetry-summary-v1-54sessions.json
