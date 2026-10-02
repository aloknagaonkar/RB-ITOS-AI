Branch C V2.6 — Original Sequence + Upward WMA21 Slope

This audit returns to the broader sequence used before the special
same-candle crossover study.

Sequence
--------
1. RSI crosses EMA3 upward -> ARMED
2. RSI crosses WMA21 upward -> ACTIVE_SETUP
3. ACTIVE_SETUP + RSI > WMA21 + RSI > 50 -> bullish candidate
4. NEW FILTER: WMA21[t] > WMA21[t-1]
5. EMA3 > WMA21 -> STRONG_BULLISH (state relation; no fresh EMA cross required)
6. Full alignment remains diagnostic.

Important
---------
- EMA3↑WMA21 on the same candle is NOT required.
- EMA3 may already be above WMA21.
- RSI may cross WMA below 50 and become BULLISH later when RSI rises above 50,
  as long as the setup remains active.
- WMA slope means exactly current WMA21 minus previous 5m WMA21.
- No arbitrary minimum positive slope threshold is introduced.
- Existing two-stage RSI/WMA weakening/end behavior is retained.

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_original_sequence_wma_slope_v2_6.py -v

Run 120-session audit
---------------------
python scripts/validate_hilega_milega_original_sequence_wma_slope_v2_6.py \
  --end-date 2026-09-21 \
  --trading-sessions 120 \
  --calendar-lookback-days 190 \
  --intraday-date 2026-09-21

Outputs
-------
data/historical-evidence/branch-c-original-sequence-wma-up-v2-6.csv
data/historical-evidence/branch-c-original-sequence-wma-not-up-v2-6.csv
