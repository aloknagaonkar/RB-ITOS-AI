# P3H.5.1 — July 21 Futures Coverage Repair

The canonical 90-session replay found 89 sessions because 2026-07-21 is missing only from the futures development CSV.

Reuse the existing producer `midpoint_v2_nifty_futures_vwap_v1.py`; do not invent a second futures methodology.

## 1. Generate only July 21 to a temporary file

```bash
printf '2026-07-21\n' > /tmp/p3h51-july21-date.txt

set -a
source .env
set +a

python -m market_lab.midpoint_v2_nifty_futures_vwap_v1 \
  --session-dates-file /tmp/p3h51-july21-date.txt \
  --output /tmp/p3h51-july21-futures.csv
```

This uses the external Upstox API and may consume provider quota.

## 2. Inspect the generated patch

```bash
head -3 /tmp/p3h51-july21-futures.csv
tail -3 /tmp/p3h51-july21-futures.csv
wc -l /tmp/p3h51-july21-futures.csv
```

## 3. Create a merged candidate

```bash
python -m market_lab.p3h51_july21_futures_coverage_repair_v1 \
  --patch-csv /tmp/p3h51-july21-futures.csv \
  --output /tmp/p3h51-futures-development-merged.csv
```

## 4. Verify the canonical population

```bash
python -m market_lab.historical_multi_session_replay_cli_v1 \
  --universe-only \
  --futures-csv /tmp/p3h51-futures-development-merged.csv
```

It must report exactly 90.

## 5. Only then replace the canonical CSV

```bash
cp data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  /tmp/midpoint-v2-nifty-futures-vwap-v1-development.before-p3h51.csv

cp /tmp/p3h51-futures-development-merged.csv \
  data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv
```

Then rerun `--universe-only` without overrides.
