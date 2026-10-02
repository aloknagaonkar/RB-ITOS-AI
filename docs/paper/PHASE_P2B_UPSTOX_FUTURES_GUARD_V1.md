# Phase P2B — Upstox Live NIFTY Futures + Production Guards

This phase connects the validated futures-VWAP calculation to Upstox's current public APIs.

## Upstox endpoints

Instrument resolution:
- `GET /v2/instruments/search`
- query=NIFTY
- exchanges=NSE
- segments=FO
- instrument_types=FUT
- current_month, with next_month fallback
- exact post-filter: `underlying_key == NSE_INDEX|Nifty 50`,
  `underlying_symbol == NIFTY`, `segment == NSE_FO`, `instrument_type == FUT`
- choose earliest non-expired expiry

Intraday candles:
- `GET /v3/historical-candle/intraday/{instrument_key}/minutes/5`
- candle timestamp is interval START
- response order is normalized ascending
- only completed 5m candles are accepted by the existing VWAP feature engine

## Production guards

`EXPIRED_OPTION_EXPIRY`
- configured option expiry is before today's IST date
- new paper entries blocked

`FUTURES_VWAP_MISSING`
- no current futures VWAP
- new paper entries blocked

`FUTURES_CANDLE_NOT_COMPLETED`
- causal violation
- new paper entries blocked

`FUTURES_VWAP_STALE`
- latest completed futures input exceeded the configured age allowance
- new paper entries blocked

## Important

This phase still does not place a paper entry.

Run the live diagnostic first. It resolves the active NIFTY future, downloads today's
5m candles, and prints only the latest completed cumulative VWAP feature.

```bash
python -m market_lab.upstox_live_futures_v1 diagnose
```

Do not paste your Upstox token.
