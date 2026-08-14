# Sprint 4.2.6 — Out-of-Sample Validation

Install over Sprint 4.2.5.

## New UI

`Shadow Directional -> Out-of-Sample Validation`

Recommended first date range:

`2026/07/16 to 2026/08/13`

## Compared groups

- `BASELINE`
- `BULLISH_ONLY`
- `BULLISH_BREAKOUT`
- `CALIBRATED_BULLISH_BREAKOUT`

## Default calibrated rule

- decision already filtered to `STRONG_SHADOW_SIGNAL`;
- direction is `BULLISH`;
- breakout or `SWING_HIGH_BREAKOUT`;
- ADX slope > `2.136`;
- directional displacement ATR > `2.445`;
- evidence includes:
  - `ADX_RISING`
  - `SWING_HIGH_BREAKOUT`
  - `POSITIVE_ATR_DISPLACEMENT`

## Promotion gates

- at least 20 resolved 30-minute signals;
- at least 60% 30-minute accuracy;
- false rate no more than 40%;
- MFE/MAE ratio at least 1.30;
- at least two represented regimes;
- no single trading day contributes more than 35% of resolved signals.

## Files

- `red_bar_lab/services/shadow_out_of_sample_validation.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_shadow_out_of_sample_validation.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_shadow_out_of_sample_validation.py `
  red_bar_lab/tests/test_shadow_directional_candle_loading.py -q
```

Execution remains blocked.
