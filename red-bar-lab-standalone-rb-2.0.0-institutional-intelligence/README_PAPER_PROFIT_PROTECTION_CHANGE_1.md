# Paper Trading Quick Fix — Change 1: Profit Protection

This package patches:

`red_bar_lab/execution/exit_engine.py`

## New protection stages

- Peak reaches **+5%** → effective stop moves to entry.
- Peak reaches **+8%** → effective stop locks at least **+2%**.
- Peak reaches **+12%** → trailing protection starts.
- Trailing stop remains **5% below the highest recorded option premium**.
- Existing `protected_stop_price` or `effective_stop` is included as a floor, so protection never moves backward.

## Apply

From the project root:

```powershell
python .\apply_profit_protection_change_1.py
```

The script creates this backup once:

```text
red_bar_lab/execution/exit_engine.py.before_profit_protection
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_paper_profit_protection_change_1.py -q
```
