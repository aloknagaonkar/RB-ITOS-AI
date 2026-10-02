# OI_FUTURES_VWAP_STANDALONE_V1

A standalone research strategy with **no midpoint structure and no T+3**.

## Frozen V1 logic

Bullish:

```text
CE 5m state = LONG_BUILDUP
PE 5m state = SHORT_BUILDUP
NIFTY FUT close > prospective session VWAP
=> BUY exact moving-ATM CE at next-minute OPEN
```

Bearish:

```text
CE 5m state = SHORT_BUILDUP
PE 5m state = LONG_BUILDUP
NIFTY FUT close < prospective session VWAP
=> BUY exact moving-ATM PE at next-minute OPEN
```

Signal generation is transition-based:

- first minute entering confluence => signal
- persistent same-direction confluence => no duplicate signal
- confluence break => reset
- later re-entry into confluence => new signal
- direct bullish/bearish flip => new signal

No T+1, no T+3, no RED/GREEN reference candle, no midpoint/boundary,
no VWAP-distance threshold, no VWAP slope, no EMA/RSI/MACD.

This initial study uses exact passive option returns at 1m/3m/5m/10m/15m,
with the same 0.5 percentage-point round-trip cost. Managed exits should be
replayed only after we know whether the standalone entry engine has merit.

## Install / copy

Copy these files into the repo:

```text
backend/market_lab/oi_futures_vwap_standalone_v1.py
tests/test_oi_futures_vwap_standalone_v1.py
README_OI_FUTURES_VWAP_STANDALONE_V1.md
```

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_oi_futures_vwap_standalone_v1.py -v
```

Expected: 3 passed.

## Run

The NIFTY futures VWAP CSV already created by the previous study is reused.
Do not download it again.

```bash
python -m market_lab.oi_futures_vwap_standalone_v1 \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --option-ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --option-ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --option-ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --option-ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --option-ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --output data/historical-evidence/oi-futures-vwap-standalone-v1-development.json
```

## Compact result

```bash
jq '{
  research_version,
  strategy_definition,
  source_schema,
  summary,
  block_summaries,
  direction_summaries,
  sep7_signals,
  governance
}' \
data/historical-evidence/oi-futures-vwap-standalone-v1-development.json
```

## Interpretation

Primary questions:

1. Is the standalone population profitable at 5m/10m/15m?
2. Does one direction dominate?
3. Are results positive across OOS_A/B/C/D or concentrated in one block?
4. How many signals does transition-based emission generate per 99 sessions?
5. Does Sep 7 generate an early bearish signal before the old T+3 logic?

Do not add filters after seeing V1. If this entry engine is promising, the
next controlled experiment is the frozen exit-policy replay.
