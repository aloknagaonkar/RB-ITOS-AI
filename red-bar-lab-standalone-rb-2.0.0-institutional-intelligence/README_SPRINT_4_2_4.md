# Sprint 4.2.4 — Validation Dashboard and Calibration Guardrails

Install over Sprint 4.2.1 through Sprint 4.2.3.2.

## Adds

- multi-day replay across a selected date range;
- weekday session selection;
- 5m/15m/30m accuracy;
- false-transition rate;
- MFE/MAE;
- breakdown by direction;
- breakdown by regime;
- confidence-band performance;
- promotion gate warnings;
- CSV export;
- execution remains blocked.

## Initial promotion gates

- minimum 100 evaluated transitions;
- minimum 20 trading sessions;
- minimum 60% 30-minute accuracy;
- maximum 40% false-transition rate;
- average MFE greater than average MAE;
- both bullish and bearish samples represented;
- no single regime contributes 80% or more of resolved results.

## Files

- `red_bar_lab/services/shadow_directional_validation.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_shadow_directional_validation.py`

## Validate

```powershell
python -m pytest red_bar_lab/tests/test_shadow_directional_validation.py -q
```

Restart Streamlit and open:

`Shadow Directional -> Multi-Day Validation`
