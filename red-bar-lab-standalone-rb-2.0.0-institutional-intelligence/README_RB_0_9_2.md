# RB-0.9.2 — Institutional Execution Committee

RB-0.9.2 adds an evidence-driven final execution layer on top of the existing Red Bar rule engine, Opportunity Extension, RB-0.9.1 Performance Trade Selection, paper execution safety controls, and Paper Exit Engine.

## What changed

- Rank is discovery order only; there is no Rank-1-only execution rule.
- There is no fixed maximum number of trades.
- Every candidate must first pass the existing Performance Trade Selection gates.
- The Institutional Execution Committee then calculates:
  - estimated execution probability,
  - expected value using configured target and stop,
  - intelligence consensus score,
  - adaptive historical-evidence weight,
  - adaptive module reliability weights from persisted intelligence evidence when available.
- Default final committee gates:
  - estimated execution probability >= 70%,
  - expected value > 0%,
  - all existing Performance Trade Selection gates remain satisfied.
- Qualified candidates are ordered by expected value, then probability, then TSS. This ordering is not a trade-count limit.

## Evidence safety

Probability is an estimate, not a guaranteed or calibrated win probability. With sparse historical evidence the model shrinks history and module reliability toward a neutral prior. As closed paper-trade evidence grows, empirical history receives more authority and can either raise or lower an optimistic rules-only estimate.

The existing Shadow Intelligence engine still has no direct order authority. RB-0.9.2 consumes its persisted evidence through a separate execution committee. Candidate-specific Greeks are only reused for Rank #1 because historical Shadow Intelligence currently persists Rank #1 for validation integrity; other ranks do not inherit Rank #1 Greeks.

## New persistence

New table: `institutional_execution_evaluations`

Per candidate it records probability, EV, rule quality, opportunity score, historical score, TSS, intelligence score, adaptive history weight, module reliability JSON, eligibility, decision and reason.

Paper execution orders additionally retain:

- `execution_probability_pct`
- `expected_value_pct`
- `intelligence_score`

## UI

Paper Trading now includes **Institutional Execution Committee** with:

- candidate rank and symbol,
- estimated execution probability,
- expected value,
- intelligence score,
- rule/opportunity/history/TSS scores,
- adaptive history weight,
- Execute YES/NO and reason,
- expandable adaptive intelligence module weights.

Stale UI wording stating that execution is locked to Rank #1 has been removed.

## Validation

`pytest -q`

Result: **200 passed**.
