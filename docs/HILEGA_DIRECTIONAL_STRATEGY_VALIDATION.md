# Hilega-Milega Directional Shadow — Validation Baseline

This document records the strategy currently exposed by the live and historical
validation workspace. It is a testing baseline, not an execution authorization.

## Strategy V2 observation test

V2 is a separate historical/observation test and does not replace the current
live strategy. Entry checks add a strict WMA(21) slope condition, calculated from
the current completed 5-minute candle and the immediately previous completed
5-minute candle:

- Bullish entries require current WMA(21) > previous WMA(21).
- Bearish entries require current WMA(21) < previous WMA(21).
- Equal values are flat and fail the entry gate.
- There is no minimum slope threshold; any strict non-zero difference qualifies.
- Entries with unavailable prior/current WMA values fail closed.

Historical replay labels each row with current/prior WMA, signed slope change,
directional slope pass/fail, and any rejection reason. The V2 replay UI reads
cached candles only; it does not call a broker or create option orders. The
recorded live strategy selection remains unchanged.

## Safety

- Observation only.
- `execution_enabled = false`.
- `paper_order_enabled = false`.
- `quantity = None`.
- One directional owner can be active at a time.
- A same-candle direction reversal is blocked.

## Indicators

The strategy operates on completed five-minute NIFTY candles and calculates:

- RSI(9)
- EMA(3) of RSI(9)
- WMA(21) of RSI(9)

Historical replay must use only information available at the selected completed
candle. It must not read a later candle to classify an earlier decision.

## Bullish path

1. Opening confirmation uses the 09:15, 09:20 and 09:25 completed bars:
   full bullish alignment at 09:15, RSI above WMA at 09:20, and RSI above WMA
   at 09:25.
2. The non-opening path arms when RSI crosses EMA(3) upward.
3. Route A enters on the same completed candle when RSI is above 50 and above
   WMA(21).
4. Route B enters after arming when RSI is rising, EMA(3) is rising, and either
   RSI or EMA(3) is above WMA(21).
5. The structural exit is the first completed RSI cross below WMA(21).
6. Bullish option observation uses CE ATM-2, ATM-1, ATM, ATM+1 and ATM+2.

## Bearish path

The bearish path mirrors the bullish path:

1. Opening confirmation uses bearish alignment and RSI below WMA.
2. The non-opening path arms when RSI crosses EMA(3) downward.
3. Route A requires RSI below 50 and below WMA(21).
4. Route B requires falling RSI, falling EMA(3), and either RSI or EMA(3)
   below WMA(21).
5. The structural exit is the first completed RSI cross above WMA(21).
6. Bearish option observation uses PE ATM-2, ATM-1, ATM, ATM+1 and ATM+2.

## Ownership and cutoff

- Opposite-direction arming remains informational while another direction owns
  the trade lifecycle.
- At 14:55 IST an active shadow is valued at the exact cutoff open when that
  evidence is available.
- No new entry is accepted after the cutoff.

## Historical replay contract

- The Hilega page contains `Live shadow` and `Historical replay` modes.
- Recorded directional live audit is authoritative for completed live dates.
- A session becomes `COMPLETE` when its `DIRECTIONAL_SESSION_CUTOFF` record is
  processed; no copying or duplicate publishing is required.
- Current/partial sessions refresh every 60 seconds in the historical view.
- Rich directional replay evidence is preferred when already materialized.
- Older research-only sessions remain visibly labelled `SUMMARY`; missing
  candle, option or premium evidence is never synthesized.
- Historical option panels show the exact audited CE/PE lifecycle when present,
  including all five legs, timestamps, premiums, current/realized points, MFE
  and MAE.
