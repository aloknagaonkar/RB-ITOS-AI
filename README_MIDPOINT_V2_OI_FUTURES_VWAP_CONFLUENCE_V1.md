# MIDPOINT V2 OI + NIFTY FUTURES VWAP CONFLUENCE V1

Research-only addition.

Question:

Does existing STRONG directional OI become more useful when the active NIFTY
futures contract is on the same side of its prospective session VWAP?

Frozen V1 study rule:

- BULLISH:
  - existing structural T+3 = BULLISH
  - existing OI = STRONG_BULLISH
  - NIFTY FUT close > session VWAP at the same decision timestamp
- BEARISH:
  - existing structural T+3 = BEARISH
  - existing OI = STRONG_BEARISH
  - NIFTY FUT close < session VWAP at the same decision timestamp

No slope, no VWAP-distance threshold, no second-bar confirmation, no EMA/RSI/MACD,
no stop change, and no entry-time change.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_midpoint_v2_oi_futures_vwap_confluence_v1.py -v
```

Expected: 2 passed.

## Build session-date file from development evidence

```bash
python - <<'PY'
import json
from pathlib import Path

src = Path("data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json")
obj = json.loads(src.read_text())
allowed = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
dates = set()

def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)

for r in walk(obj):
    if str(r.get("block")) in allowed and r.get("session_date"):
        dates.add(str(r["session_date"]))

out = Path("data/historical-evidence/midpoint-v2-development-session-dates.txt")
out.write_text("\n".join(sorted(dates)) + "\n")
print("session_count:", len(dates))
print(out)
PY
```

## Collect NIFTY FUT 1m OHLCV + prospective VWAP

```bash
set -a
source .env
set +a

python -m market_lab.midpoint_v2_nifty_futures_vwap_v1   --session-dates-file data/historical-evidence/midpoint-v2-development-session-dates.txt   --output data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv
```

## Run confluence study

```bash
python -m market_lab.midpoint_v2_oi_futures_vwap_confluence_v1   --events data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json   --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json   --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv   --output data/historical-evidence/midpoint-v2-oi-futures-vwap-confluence-v1-development.json
```

If `strong_oi_only.trade_count` is zero, the supplied events file does not contain
the existing STRONG_BULLISH / STRONG_BEARISH labels. Do not infer OI from absence.
Use the already existing OI-enriched evidence artifact instead.

## Compact output

```bash
jq '{
  research_version,
  rules,
  summary,
  block_summaries,
  sep7_reference,
  governance
}' data/historical-evidence/midpoint-v2-oi-futures-vwap-confluence-v1-development.json
```
