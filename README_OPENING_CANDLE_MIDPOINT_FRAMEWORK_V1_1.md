# Opening Candle Midpoint Framework V1.1 patch

Replace the existing framework file and test, then rerun the same 100-session
research under a new V1.1 output filename.

Expected integrity check after rerun:

```text
sum(RED reclaim outcomes)   == RED_BREAK_BULLISH_RECLAIM count
sum(GREEN reclaim outcomes) == GREEN_BREAK_BEARISH_RECLAIM count
```

Do not derive reclaim thresholds from the old V1 output.
