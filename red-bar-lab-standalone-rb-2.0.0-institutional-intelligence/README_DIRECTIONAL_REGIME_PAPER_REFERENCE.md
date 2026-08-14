# Paper Trading — Directional Regime Intelligence Reference

This change adds **Directional Regime Intelligence** as an additional
read-only reference for every existing Paper Trading bullish/bearish signal.

## Current behavior

The existing reference-level signal remains the parent execution signal:

`midpoint setup → 1m confirmation → BULLISH/BEARISH → CE/PE`

Directional Regime Intelligence is evaluated alongside it and records:

- `ALIGNED`
- `PARTIAL_ALIGNMENT`
- `CONFLICT`
- `NEUTRAL`
- `UNAVAILABLE`

## Important safety boundary

This version is `REFERENCE_ONLY`.

It does not:

- replace the existing signal;
- block a trade;
- approve a trade;
- change CE/PE mapping;
- change candidate score;
- change Committee eligibility;
- create a paper or live order.

It writes an auditable execution-state event named:

`DIRECTIONAL_REGIME_REFERENCE`

## Apply

From the project root:

```powershell
python .\apply_directional_regime_reference.py
```

A backup is created:

`red_bar_lab/execution/automation.py.before_directional_regime_reference`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_directional_regime_paper_reference.py -q
```

## Runtime inspection

In Paper Trading execution-state history, inspect:

- status
- regime
- bundle direction
- bundle ID
- primary setup
- alignment score
- reason
- `mode=REFERENCE_ONLY`
