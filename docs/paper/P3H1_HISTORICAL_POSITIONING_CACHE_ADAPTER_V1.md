# P3H.1 Historical Positioning Cache Adapter V1

The repository sample confirms this historical OI source shape:

- schema_version
- status=AVAILABLE
- session_date
- expiry
- wings
- strike_interval
- rows
- each row contains timestamp, spot, moving_atm, strike, strike_offset,
  CE/PE instrument keys, CE/PE close, CE/PE OI, CE/PE volume

The adapter now:

1. discovers `historical-positioning-cache*` directories
2. selects files by `session_date`
3. loads and validates row_count
4. selects the shortest non-expired historical option expiry
5. groups the rows by checkpoint timestamp
6. requires a genuine 09:20 group

No synthetic 09:20 baseline is created.

## Still required

P3H needs the exact stored historical NIFTY futures candle format before the causal VWAP adapter is wired.
Do not guess that schema.

Run:

```bash
find data -maxdepth 4 -type f | grep -Ei 'futures.*(json|csv)|future.*(json|csv)|vwap.*(json|csv)' | head -100
```

Then inspect one likely file with `head -40`.
