# P3H.4 Intrabar Option OHLC Replay V1

The historical option cache has real reconstructed 1-minute OHLC rows with:

- instrument_key
- strike
- side
- timestamp
- open/high/low/close
- volume
- open_interest
- provenance=HISTORICAL_CANDLE_RECONSTRUCTION

## What improves over P3H.3

P3H.3 used checkpoint close for every risk decision.

P3H.4 keeps the P3H.3 entry-price proxy because historical bid/ask is still not
available, but it uses 1-minute option OHLC for risk exits.

Frozen stop semantics implemented:

- initial hard stop = -5%
- breakeven armed after +5%
- trailing armed after +10%
- trailing distance = 3%
- no maximum holding time
- newly raised stop activates on the NEXT minute bar
- if next bar OPEN gaps through an active stop, exit at OPEN
- otherwise if LOW touches an active stop, exit exactly at the stop price

A stop activated by the HIGH of a candle is never allowed to also trigger on
the LOW of that same candle. This removes ambiguous same-bar lookahead.

## Important remaining approximation

Entry still uses the exact ATM option checkpoint close at P2 because the
historical cache does not contain bid/ask. Therefore this is materially better
for exits, but still not production ASK/BID fill parity.

## Run

```bash
python -m market_lab.historical_option_intrabar_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events exits
```
