# Integration checklist

This bundle intentionally implements the strategy core without guessing your existing
paper-execution interfaces.

## Connect these existing platform services

1. OI/PCR feature engine
   - produce previous/current 5m imbalance
   - PCR 5m change
   - previous/current session imbalance
   - CE/PE 5m deltas

2. Futures VWAP service
   - provide only the most recent fully completed futures 5m candle
   - include candle timestamp / availability timestamp / close / VWAP

3. Strategy scheduler/state
   - call `on_p1_checkpoint(...)` at a completed OI checkpoint
   - if decision is `WAIT_P2`, retain pending state
   - call `on_p2_checkpoint(...)` only at the next completed checkpoint

4. Option selector
   - compute ATM at P2 decision time
   - exact ATM only
   - no nearest-strike fallback

5. Paper execution
   - accept only `ENTER_CE_PAPER` / `ENTER_PE_PAPER`
   - reject if mode is not PAPER
   - enforce max 4 open positions globally

6. Position risk
   - instantiate one `PremiumExitState` per paper position
   - no max-holding timer

## Do not enable paper mode merely by merging this bundle.

After tests pass, wire it to the repository's actual paper executor and expose a
separate manual `PAPER_ENABLE` control. Live remains disabled.
