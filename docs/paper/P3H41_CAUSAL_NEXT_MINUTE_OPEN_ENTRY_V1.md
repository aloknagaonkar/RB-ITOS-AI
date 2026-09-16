# P3H.4.1 Causal Next-Minute Open Entry

P3H.4 validated 1-minute intrabar stop handling, but review of the Aug-25
output exposed a remaining causality issue:

P2 is confirmed at a checkpoint timestamp, so using that same checkpoint's
option close as the simulated entry can use information from the decision bar.

P3H.4.1 fixes this.

## Historical entry rule

- P2 confirmed at time T
- exact ATM CE/PE is already known from P2
- find the first historical 1-minute candle with timestamp > T
- simulated entry = that candle OPEN
- initial -5% hard stop is active immediately in that entry minute
- BE/trailing stops raised from that minute's HIGH activate only next minute

This is closer to causal execution and does not reuse the P2 checkpoint close.

## Remaining approximation

Historical bid/ask is unavailable, so next-minute option OPEN is still an
execution proxy. Production remains ASK entry and BID exit/risk monitoring.

## Summary improvement

The report now separates:
- winners
- losers
- breakeven
- entry rejects
