# Phase P2 — Live OI + Futures VWAP Feature Engine V1

This phase implements the causal feature calculations only.

## OI rules

Recent 5m context:
- moving ATM±2
- compare the SAME physical 5 strikes at T vs T-5
- imbalance = PE 5m OI delta - CE 5m OI delta
- PCR change is current ATM±2 PCR minus prior checkpoint PCR on the same 5 strikes

Session context:
- fixed 09:20 ATM±2 strike basket
- compare current OI vs 09:20 OI on those exact physical strikes
- session imbalance = PE session delta - CE session delta
- preserve previous session-imbalance checkpoint for P1 direction test

## Futures VWAP rules

- 5m futures candle timestamps are interval START
- only completed candles are usable
- same-label in-progress candle is forbidden
- cumulative session VWAP proxy = sum(((H+L+C)/3)*volume)/sum(volume)
- this is a candle/volume VWAP proxy, not exchange trade-level VWAP

## Important limitation of this bundle

It does NOT yet fetch live NIFTY futures candles from Upstox.

The existing repository gateway shown so far does not expose a live intraday futures-candle method,
and this bundle deliberately does not guess undocumented/current endpoint behavior.

Phase P2A therefore freezes/test-validates the calculations. The next narrow integration step is to
add the provider adapter against the exact Upstox endpoint/data shape available in the repository/environment.

## No paper entries yet

Paper control must remain disabled until:
1. live futures adapter exists
2. stale-data checks exist
3. P1->VWAP->P2 evaluator is connected
4. exact ATM quote resolution is connected
