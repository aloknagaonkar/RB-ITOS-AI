# RB-0.9.1 — Performance-Driven Multi-Trade Selection

## Purpose
RB-0.9.1 removes the fixed Rank #1 paper-execution rule. Candidate ranking remains intact for discovery and transparency, but every candidate is now independently evaluated by a deterministic Performance Trade Selection Engine.

There is no fixed maximum-trade count. Qualified candidates execute in descending Trade Selection Score order until a real execution safety constraint (available paper capital, candidate-level duplicate protection, invalid quote, stale-opportunity rejection, or other existing safety rule) prevents an entry.

## Trade Selection Score (TSS)
The first deterministic TSS combines:
- 35% candidate quality
- 20% Opportunity Health
- 10% reward/risk
- 25% historical performance
- 10% execution quality (spread + liquidity)

Historical performance includes sample size, win rate, average return, profit factor, expectancy, average MFE and average MAE for the same option type and entry mode (Fresh Signal vs Opportunity Extension).

## Evidence safety
Until at least 10 comparable closed paper trades exist, the historical component uses a neutral prior (50/100). The system does not invent a probability from insufficient evidence.

Once evidence is mature (default 10+ trades), execution also requires:
- historical win rate >= 45%
- profit factor >= 1.10
- positive expectancy

These thresholds are deterministic defaults intended for paper validation and later optimization.

## Multi-trade duplicate protection
The old uniqueness rule `(signal_id, account_id)` is migrated to `(signal_id, account_id, instrument_token)`. This allows multiple independently-qualified strikes from the same Red Bar signal while preventing the same candidate from being reopened repeatedly for that signal.

## Existing protections retained
- Market-hour gate
- Signal freshness logic
- Opportunity Extension for stale signals
- Red Bar structure/opposite-signal validation
- Candidate score threshold
- Spread/liquidity validation
- Option quote validation
- Available paper capital
- Existing stop/target logic
- Paper Exit Engine and lifecycle monitoring
- Live execution remains disabled

## UI
A new `Performance Trade Selection` panel shows all candidates from the latest evaluation with:
- Rank
- Candidate
- Candidate Score
- Opportunity Health
- Reward Remaining
- Reward/Risk
- Historical sample size
- Historical Win Rate
- Profit Factor
- Expectancy
- MAE / MFE
- TSS
- Execute YES/NO
- Reason

## Database
New table: `trade_selection_evaluations`.

Paper execution orders now record:
- candidate_rank
- candidate_score
- selection_score
- historical_win_rate_pct
- historical_profit_factor
- historical_expectancy_pct
- historical_sample_size

## Validation
`196 passed`
