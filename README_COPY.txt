Branch C V2.5 — Real-data Same-candle Crossover Audit

Purpose
-------
Test historical Nifty data for cases where:

1. RSI↑EMA3 happened earlier and ARMED the setup.
2. On a later 5-minute candle:
   RSI↑WMA21
   AND
   EMA3↑WMA21
   happen on the SAME candle.
3. RSI > 50.
4. The state is immediately classified BULLISH + STRONG_BULLISH.

The script scans the same 120-session history used by the previous audits.

For every same-candle event it prints:
- date
- signal candle time
- Nifty close
- RSI9
- EMA3
- WMA21
- RSI-WMA distance
- EMA-WMA distance
- bullish-end time
- Nifty points from signal to bullish end

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_same_candle_real_data_v2_5.py -v

Run audit
---------
python scripts/validate_hilega_milega_same_candle_real_data_v2_5.py   --end-date 2026-09-21   --trading-sessions 120   --calendar-lookback-days 190   --intraday-date 2026-09-21

Output
------
data/historical-evidence/branch-c-same-candle-real-data-v2-5.csv
