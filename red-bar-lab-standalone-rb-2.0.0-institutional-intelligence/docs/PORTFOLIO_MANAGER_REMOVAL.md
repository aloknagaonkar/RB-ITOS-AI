# Portfolio Manager Trade Blocking Removal

## Decision

The Institutional Execution Committee is the final business approval gate for paper trades.

Candidates approved by the Committee must proceed to execution. Portfolio-level limits must not convert an approved candidate to `WAITING`.

## Compatibility approach

The existing `PortfolioRiskManager` interface is retained temporarily so current automation, configuration, imports, dashboards and historical records continue to work without a disruptive rewrite.

Its admission method is now a pass-through:

- every candidate received from the Committee is returned as `APPROVED`;
- open-trade, same-direction, capital, risk and opportunity-health limits are no longer blocking conditions;
- capital and risk totals continue to be calculated for compatibility and visibility;
- the recorded reason is `COMMITTEE_APPROVED_PORTFOLIO_BYPASSED`.

## Execution flow

```text
Candidate and opportunity checks
        ↓
Institutional Execution Committee
        ↓
Committee APPROVED
        ↓
Compatibility portfolio pass-through
        ↓
Paper trade execution
```

Committee rejection, duplicate protection, invalid market data, terminal opportunities, market-hours rules and technical execution errors remain unaffected.
