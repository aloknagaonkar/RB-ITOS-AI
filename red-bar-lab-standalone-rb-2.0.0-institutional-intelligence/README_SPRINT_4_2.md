# Sprint 4.2 — Shadow Directional Transition Engine

This package implements the additive Sprint 4.2.1 foundation.

## Included

- `directional_features.py`
  - EMA10/EMA30
  - EMA slope and acceleration normalized by ATR
  - DMI (+DI/-DI) and ADX
  - ATR-normalized displacement
  - range expansion/compression
  - swing breakout/breakdown
  - basic price structure
  - volume ratio

- `directional_regime.py`
  - trending bullish/bearish
  - range
  - compression
  - expansion
  - pullback
  - reversal risk
  - unstable

- `directional_transition.py`
  - transparent 100-point bullish/bearish score
  - transition type and confidence
  - optional Red Bar supporting evidence
  - execution is always blocked

- `shadow_directional_service.py`
  - observation-only service façade

- deterministic tests

## Installation

Copy the `red_bar_lab` folder into:

`red-bar-lab-standalone-rb-2.0.0-institutional-intelligence/`

No existing execution file is replaced.

## Validation

```powershell
python -m pytest red_bar_lab/tests/test_directional_features.py red_bar_lab/tests/test_directional_transition.py -q
```

## Safety boundary

This engine does not import or invoke candidate selection, committee, portfolio,
paper order, live order, stop-loss, target, or exit logic.
