# RB-1.5.0 — Institutional Portfolio Execution

RB-1.5.0 changes the entry-side execution architecture while preserving the existing exit engine.

## What changed

- **Shadow remains informational only.** It has zero execution weight, bonus, penalty, or veto authority.
- **Signal age is informational.** The original 180-second freshness window remains visible for diagnostics but age alone does not expire or reject a candidate.
- **Opportunity Health is authoritative current-market evidence.** The 0–100 health model uses Structure 20, VWAP 15, EMA 15, Momentum 15, Volume 10, OI 10, Liquidity 10, Spread 5.
- **Multiple candidates can execute.** Rank is priority/discovery order only. Every candidate is evaluated independently.
- **Portfolio Risk Manager added.** Committee-qualified candidates are admitted in priority order subject to open-position, same-direction, capital and aggregate stop-risk budgets. Qualified trades that do not fit remain WAITING/watchlist and can be reconsidered later.

## Default portfolio policy

- Maximum open paper trades: 5
- Maximum same-direction (CE or PE) trades: 3
- Maximum deployed capital: 40% of paper capital
- Maximum aggregate stop risk: 2% of paper capital
- Minimum Opportunity Health for portfolio admission: 75

These are portfolio admission controls, not changes to candidate scoring or exit logic.

## Unchanged

Primary Decision Engine scoring, Shadow calculations/storage, Committee confidence/expectancy rules, duplicate checks, paper-order mechanics, stop loss, break-even, trailing stop, thesis/technical exit, targets, EOD exit, historical replay and learning remain in place.

## Validation

229 tests pass, including new RB-1.5.0 tests for age-neutral lifecycle behavior, multi-candidate admission, best-first priority, risk-budget watchlisting, and Rank #1 not being privileged when its Opportunity Health is weaker.
