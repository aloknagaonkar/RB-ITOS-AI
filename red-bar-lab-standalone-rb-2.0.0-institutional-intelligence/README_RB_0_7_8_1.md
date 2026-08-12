# RB-0.7.8.1 — Performance Optimization

RB-0.7.8.1 focuses on reducing Paper Trading page rerun cost without changing
the Current Decision Engine, candidate ranking rules, automatic paper entry
rules, exit rules, or Shadow execution authority.

## 1. Persistent Upstox market stack

The Paper Trading page previously recreated:

- RedBarUpstoxService
- UnifiedUpstoxMarketIntelligenceService
- UpstoxPaperMarketAdapter

on every Streamlit rerun.

They are now retained using `st.cache_resource`.

This allows the existing in-memory option-chain and option-contract caches to
survive Streamlit reruns.

### Market snapshot TTL

The persistent Unified Upstox intelligence service uses a 10-second snapshot
TTL.

This means rapid UI reruns can reuse one consistent market snapshot instead of
re-requesting the option chain every time.

## 2. Persistent database facade

The RedBarDatabase facade is now reused with `st.cache_resource`.

The database methods continue to open their normal SQLite connections; this
change avoids repeatedly recreating and initializing the facade during every
UI rerun.

## 3. Short-lived option candle cache

`UpstoxPaperMarketAdapter` now keeps a 15-second candle cache keyed by:

- instrument token
- interval
- from date
- to date

This is especially useful because candidate ranking may already have requested
the same option candle that the Candidate Workbench wants to display.

Switching between recently ranked candidates can therefore reuse those candles
instead of immediately calling the Upstox candle endpoint again.

## 4. Candidate Workbench Streamlit Fragment

The entire Top-5 inspection surface is now isolated with `@st.fragment`.

The fragment contains:

- Top-5 table
- Rank #1-#5 radio
- selected candidate metrics
- score breakdown
- Greeks
- Why Rank #1 / Why Not Rank #1
- selected option candle
- Execution vs Inspection
- Compare Two Candidates

Changing the inspected Rank reruns this fragment only.

It does not need to rerun:

- Current Decision Engine
- Shadow Intelligence
- paper account summary
- open-position section
- execution diagnostics
- journal
- the rest of the page

## 5. Lazy Trade Lifecycle

Detailed Trade Lifecycle & Provenance previously executed many per-trade
database lookups on every normal Paper Trading refresh.

It is now behind:

`Load Trade Lifecycle & Provenance`

Default: OFF.

The section is queried/rendered only when the user explicitly enables it.

## 6. Lazy Advanced Audit

The following heavy sections are now grouped behind:

`Load Advanced Diagnostics, Timeline & Journal`

Default: OFF.

This avoids loading them during ordinary market monitoring:

- Why Was / Wasn't a Paper Trade Executed?
- Execution Timeline
- closed Paper Trade Journal & Statistics

## 7. What still loads immediately

The real-time trading surface still loads normally:

- market/account health
- latest Red Bar signal
- Trader Recommendation
- Top-5 ranking snapshot
- Candidate Workbench
- Current Decision Engine
- Shadow Intelligence
- open paper positions
- Rank #1 execution evidence

This keeps the important operational information visible.

## 8. Trading logic remains frozen

RB-0.7.8.1 does NOT change:

- Red Bar confirmation rules
- market-hours gate
- signal freshness
- duplicate protection
- CE/PE direction mapping
- candidate-score formula
- minimum score
- Rank #1 execution rule
- stop / target / EOD exit logic
- Shadow Intelligence execution impact

Rank #1 remains the only automatic paper execution candidate.

## Expected impact

Actual speed depends on Upstox latency, local machine performance, SQLite
history size, and whether a market request is already cached.

The intended behavior is:

- Candidate Rank switch: fragment-only rerun
- repeated refresh inside 10-second market TTL: reuse market snapshot
- repeated candle request inside 15 seconds: reuse candle payload
- normal page refresh: no lifecycle/journal N+1 queries unless requested

## Validation

The release includes regression checks for:

- cached service architecture
- Streamlit fragment workbench
- lazy audit controls
- candle-cache reuse
- Rank #1 remaining the execution candidate
- all prior trading behavior tests
