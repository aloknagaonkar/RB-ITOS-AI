# RB-0.7.7 — Candidate Inspection & Explainable Ranking

RB-0.7.7 adds interactive inspection for all Top-5 ranked CE/PE candidates
without changing the frozen automatic paper execution rules.

## Execution safety

Rank #1 remains the ONLY automatic paper execution candidate.

Selecting Rank #2, #3, #4 or #5:

- does not change the execution candidate
- does not change BUY/WAIT
- does not modify score thresholds
- does not open or close a paper trade
- does not change Shadow Intelligence
- is inspection only

Live execution remains hard-disabled.

## Interactive Top-5 Candidate Table

The Top Ranked Candidates table now supports single-row selection.

Click any candidate row to inspect it.

If the installed Streamlit build does not support dataframe row selection,
the UI automatically falls back to a candidate dropdown.

The selected row is persisted in Streamlit session state across page reruns.

## Candidate badges

Rank #1:

`RANK #1 · EXECUTION CANDIDATE`

Ranks #2–#5:

`RANK #N · INSPECTION ONLY`

The selected inspection candidate is always visibly separated from the
automatic execution candidate.

## Selected Candidate Inspection

For any Top-5 candidate the UI now shows:

- rank
- contract
- rule score
- candidate health score
- health band
- entry reference
- stop
- target 1
- target 2
- current paper decision

## Full Score Breakdown

Every inspected candidate shows the exact existing score components:

- Spread / 15
- Liquidity / 20
- Volume / 15
- Open Interest / 10
- VWAP / 10
- EMA9 / EMA21 / 10
- Momentum / 10

These are the same components used by the frozen Current Decision Engine.

## Greeks

For every inspected candidate the UI shows:

- Delta
- Gamma
- IV
- Theta
- Vega

Greeks remain informational / Shadow evidence and do not change the Current
Decision Engine score.

## Candidate Health

RB-0.7.7 adds an inspection-only health score.

It primarily reflects normalized current rule-score components, with a small
informational Greeks-quality contribution when Greeks are available.

Health bands:

- EXCELLENT
- GOOD
- WATCH
- WEAK

Candidate Health does not affect ranking or execution.

## Why Rank #1?

When Rank #1 is inspected, the UI explicitly states that it is:

- the highest-ranked candidate
- the only automatic execution candidate

## Why Isn't Rank #N Rank #1?

For candidates #2–#5, the UI compares that candidate against Rank #1 and
reports:

- score gap
- components where it is better than Rank #1
- components where it is weaker than Rank #1
- explicit inspection-only status

This makes the ranking explainable instead of black-box.

## Strengths and Watch Items

Each inspected candidate also shows component-level strengths and weaknesses.

Examples:

- strong Liquidity
- strong Open Interest
- weak Spread
- weak VWAP alignment

## Candidate Candle Preview

The selected candidate's current intraday option chart is displayed with:

- Close
- EMA9
- EMA21
- VWAP

Metrics below the chart show:

- contract
- current close
- VWAP
- EMA9
- EMA21
- momentum

This works for Rank #1 through Rank #5.

## Existing Rank #1 Evidence

The previous `Why This Option?` evidence block is retained as:

`Why This Option? — Execution Candidate Evidence (Rank #1)`

So the execution candidate's original evidence remains visible even while the
user inspects another candidate.

## Existing engines remain unchanged

- Current Decision Engine: unchanged
- Shadow Intelligence: unchanged
- Shadow Validation: unchanged
- automatic paper execution: unchanged
- live execution: disabled

## Validation

RB-0.7.7 includes regression tests for:

- Rank #1 execution-candidate identity
- lower-rank inspection-only behavior
- comparison to Rank #1
- score-component breakdown
- clickable/single-row selection UI
- Streamlit fallback selection
- preservation of previous Paper Trading sections
- preservation of all prior tests

## Next

The next RB-0.7.7.x work can extend the read-only audit layer with:

- Trade Doctor
- Why-NOT explanations
- event stream
- portfolio timeline
- confidence drift
- trade health over time

None of those should change execution until separately validated.
