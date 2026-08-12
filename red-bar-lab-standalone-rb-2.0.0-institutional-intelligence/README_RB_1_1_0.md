# RB-1.1.0 — Adaptive Probability Voting Engine

## What changed
- Replaced the compressed composite/logistic probability model with an explainable weighted expert voting engine.
- Voting works immediately with fixed prior weights; historical evidence is not required.
- Shadow intelligence modules (PCR, OI Change, Greeks, Market Context, Structure, etc.) share an adaptive intelligence budget and learn reliability when evidence later exists.
- Candidate experts include Rule Quality, Opportunity, Spread, Liquidity, Volume, OI, VWAP, EMA, Momentum, and Historical performance.
- Added per-expert score, normalized weight, contribution points, source and detail.
- Fixed RB-1.0.0 persistence bug that caused Expected Win / Expected Loss to show None in the UI.
- Expected Win/Loss and expectancy fields are now persisted with each committee evaluation.
- Opportunity is an explicit vote and is not applied as a hidden second probability multiplier.
- Terminal invalidations remain hard: REWARD_CONSUMED, OPPOSITE_RED_BAR, STRUCTURE_INVALID.
- Existing spread/liquidity and operational safety controls remain unchanged.

## Probability
Execution Probability = weighted sum of active expert vote scores.

The dashboard includes an expanded `Probability voting breakdown` showing exactly how the probability was built.

## Validation
209 tests passed.
