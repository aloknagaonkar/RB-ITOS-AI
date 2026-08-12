# RB-1.2.0 — Primary + Shadow Agreement Engine

## Authority model

- Primary Rule Engine is authoritative for candidate confidence.
- Shadow Intelligence remains advisory and independent.
- Execution Committee applies a bounded agreement bonus or conflict penalty to Primary confidence.
- Individual shadow modules remain visible for explainability but do not directly dilute the Primary score.
- Expectancy and existing hard safety controls remain execution gates.

## Confidence model

- Shadow agrees with Primary: bonus up to +10 points, scaled by Shadow confidence.
- Shadow says WAIT: caution penalty up to -4 points, scaled by Shadow confidence.
- Shadow explicitly conflicts: penalty up to -20 points, scaled by Shadow confidence.
- Final confidence is clamped to 5–95%.

## UI

Execution Committee Dashboard now shows:
- Primary Confidence
- Shadow Decision
- Shadow Confidence
- Agreement
- Shadow Adjustment
- Final Committee Confidence
- Expectancy / Expected Win / Expected Loss

Candidate detail includes a Primary + Shadow Agreement Breakdown and a Shadow Intelligence Detail table marked advisory-only.

## Persistence

Institutional execution evaluations now persist:
- primary_decision
- primary_confidence_pct
- shadow_decision
- shadow_confidence_pct
- agreement
- shadow_adjustment_pct

Existing databases are upgraded additively through the normal schema initialization path.

## Validation

211 tests passed.
