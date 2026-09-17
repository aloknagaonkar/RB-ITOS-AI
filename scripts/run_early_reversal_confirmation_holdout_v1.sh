#!/usr/bin/env bash
set -euo pipefail
cd ~/RB-ITOS-AI
source .venv/bin/activate

pytest -q tests/test_early_reversal_confirmation_holdout_v1.py

DEV_ROWS="data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv"
HOLDOUT_DIR="data/historical-evidence/early-reversal-holdout-v1"
mkdir -p "$HOLDOUT_DIR"

python - <<'PY'
import csv, glob, json, re
from pathlib import Path

dev_rows="data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv"
out_dir=Path("data/historical-evidence/early-reversal-holdout-v1")
out_dir.mkdir(parents=True,exist_ok=True)

with open(dev_rows,newline="") as f:
    dev=sorted({r["session_date"] for r in csv.DictReader(f)})

pat=re.compile(r"oi-price-regime-audit-(\d{4}-\d{2}-\d{2})-v1-1\.json$")
available=[]
for p in glob.glob("data/historical-evidence/oi-price-regime-audit-*-v1-1.json"):
    m=pat.search(p)
    if m:
        available.append((m.group(1),p))

holdout=sorted((d,p) for d,p in available if d not in set(dev))

(out_dir/"development-dates-54.txt").write_text("\n".join(dev)+"\n")
(out_dir/"holdout-dates-frozen.txt").write_text("\n".join(d for d,_ in holdout)+"\n")
(out_dir/"holdout-audit-files.txt").write_text("\n".join(p for _,p in holdout)+"\n")

print("development sessions:", len(dev))
print("available V1.1 audit sessions:", len(available))
print("frozen holdout sessions:", len(holdout))
if not holdout:
    raise SystemExit("No non-development V1.1 audit sessions found.")
PY

mapfile -t HOLDOUT_DATES < "$HOLDOUT_DIR/holdout-dates-frozen.txt"
mapfile -t AUDITS < "$HOLDOUT_DIR/holdout-audit-files.txt"

echo "Frozen holdout dates:"
printf '  %s\n' "${HOLDOUT_DATES[@]}"

# Build the same unchanged horizon-state rows for holdout audits.
ARGS=()
for f in "${AUDITS[@]}"; do
  ARGS+=(--audit-json "$f")
done

python -m market_lab.change_pcr_validation_v1 \
  "${ARGS[@]}" \
  --rows-csv "$HOLDOUT_DIR/change-pcr-validation-rows-holdout-v1.csv" \
  --summary-json "$HOLDOUT_DIR/change-pcr-validation-summary-holdout-v1.json"

HARGS=()
for f in "${AUDITS[@]}"; do
  HARGS+=(--audit-json "$f")
done

python -m market_lab.early_reversal_confirmation_holdout_v1 \
  --rows-csv "$HOLDOUT_DIR/change-pcr-validation-rows-holdout-v1.csv" \
  "${HARGS[@]}" \
  --events-csv "$HOLDOUT_DIR/early-reversal-confirmation-holdout-v1-events.csv" \
  --summary-json "$HOLDOUT_DIR/early-reversal-confirmation-holdout-v1-summary.json"
