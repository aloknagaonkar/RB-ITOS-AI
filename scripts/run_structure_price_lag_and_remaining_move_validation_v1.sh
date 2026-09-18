#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

pytest -q tests/test_structure_price_lag_and_remaining_move_validation_v1.py

OUTDIR="data/historical-evidence/structure-price-lag-remaining-move-v1"
mkdir -p "$OUTDIR"

python - <<'PY'
import csv, json
from pathlib import Path

manifests = [
    ("OOS_E", Path("data/historical-validation/manifest-oos-e-20.json")),
    ("OOS_F", Path("data/historical-validation/manifest-oos-f-20.json")),
    ("OOS_G", Path("data/historical-validation/manifest-oos-g-20.json")),
    ("OOS_H", Path("data/historical-validation/manifest-oos-h-20.json")),
]

dates = []
rows = []
for block, path in manifests:
    data = json.loads(path.read_text())
    block_dates = []
    for s in data["sessions"]:
        d = s.get("session_date") or s.get("date")
        if d:
            block_dates.append(d)
            rows.append((block, d))
            dates.append(d)
    if len(block_dates) != 20:
        raise SystemExit(f"{path}: expected 20 sessions, got {len(block_dates)}")

unique = sorted(set(dates))
if len(unique) != 80:
    raise SystemExit(f"Expected 80 unique validation sessions, got {len(unique)}")

# Protect against overlap with 54-session development cohort if file exists.
dev_path = Path("data/historical-evidence/change-pcr-validation-rows-v1-54sessions.csv")
if dev_path.exists():
    with dev_path.open(newline="") as f:
        dev = {r["session_date"] for r in csv.DictReader(f)}
    overlap = sorted(dev.intersection(unique))
    if overlap:
        raise SystemExit(f"Validation cohort overlaps development dates: {overlap}")

out = Path("data/historical-evidence/structure-price-lag-remaining-move-v1")
(out/"validation-dates-80-frozen.txt").write_text("\n".join(unique) + "\n")
(out/"validation-dates-80-with-blocks.csv").write_text(
    "block,session_date\n" + "\n".join(f"{b},{d}" for b,d in rows) + "\n"
)

print("Frozen validation sessions:", len(unique))
print("First:", unique[0])
print("Last :", unique[-1])
PY

mapfile -t DATES < "$OUTDIR/validation-dates-80-frozen.txt"

echo
echo "Checking / generating V1.1 audits for frozen 80-session cohort..."

for d in "${DATES[@]}"; do
  json="data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json"
  csv="data/historical-evidence/oi-price-regime-audit-${d}-v1-1.csv"

  if [[ -f "$json" ]]; then
    echo "EXISTS $d"
    continue
  fi

  echo "GENERATE $d"
  python -m market_lab.oi_price_regime_transition_audit_v1_1 \
    --session-date "$d" \
    --moving-wings 5 \
    --futures-csv data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-all180.csv \
    --csv "$csv" \
    --json-output "$json"
done

ARGS=()
for d in "${DATES[@]}"; do
  f="data/historical-evidence/oi-price-regime-audit-${d}-v1-1.json"
  [[ -f "$f" ]] || { echo "Missing audit after generation: $f" >&2; exit 1; }
  ARGS+=(--audit-json "$f")
done

python -m market_lab.change_pcr_validation_v1 \
  "${ARGS[@]}" \
  --rows-csv "$OUTDIR/change-pcr-validation-rows-v1-80sessions.csv" \
  --summary-json "$OUTDIR/change-pcr-validation-summary-v1-80sessions.json"

python -m market_lab.structure_price_lag_and_remaining_move_validation_v1 \
  --rows-csv "$OUTDIR/change-pcr-validation-rows-v1-80sessions.csv" \
  "${ARGS[@]}" \
  --events-csv "$OUTDIR/structure-price-lag-remaining-move-v1-events-80sessions.csv" \
  --summary-json "$OUTDIR/structure-price-lag-remaining-move-v1-summary-80sessions.json"
