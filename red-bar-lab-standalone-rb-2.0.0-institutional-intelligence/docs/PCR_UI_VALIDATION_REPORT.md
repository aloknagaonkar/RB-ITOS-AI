# Trade Evidence page - PCR validation report

## Source files inspected

- `red_bar_lab/ui/pages/market_readiness.py` (orchestrator)
- `red_bar_lab/ui/market_direction_summary.py` (summary table)
- `red_bar_lab/ui/market_trend_research_panel.py` (tabbed PCR detail)
- `red_bar_lab/strategy/red_bar_v2.py` (new V2 PCR fields: `pcr_value`, `morning_pcr_value`)
- `red_bar_lab/strategy/red_bar_v2_futures.py` (wires PCR into V2 direction decision)

## What the page already does well

1. **Combined PCR aggregation** (`CombinedMarketPcrCalculator`) — pulls PCR from
   NIFTY 50 + BANKNIFTY + SENSEX + Top-10 constituents and reports a weighted
   index PCR with coverage % and agreement text. This is the highest-signal
   PCR number on the page.
2. **PCR freshness check** — every panel reports `FRESH / STALE / INCOMPLETE`
   using `MarketTrendResearchPolicy.maximum_source_age_seconds`. Stale rows
   are clearly marked, not silently substituted.
3. **Pre-open NSE vs Upstox** cross-check with diff % — handles the
   "NSE_ONLY / UPSTOX_ONLY / CONFLICT / ALIGNED" states explicitly.
4. **Volume Confirmation as a separate informational row** — explicitly
   captioned "Observational only. Volume confirmation does not create,
   reject, bundle, reserve or execute a trade." Good.
5. **Best-four contract selection** is opt-in (only when `preference_status == "PASSED"`)
   and never fabricates candidates.
6. **Read-only summary caption** at the bottom of the panel.

## Gaps in the current PCR presentation

### 1. "Current/Overall PCR" and "Morning Fixed-Level PCR" rows duplicate the same data source

Both rows read from `current_panel` and `morning_panel` of the
`latest_projection`. They are two snapshots of the same 5m PCR at different
windows of the day. The user can't tell from the UI whether the morning PCR
is the *opening* snapshot, the *09:15-09:20 fixed-level* PCR, or simply
the 5m candle PCR from 9:15. The column "Fixed morning strike positioning" in
the Interpretation column hints at it but doesn't explain.

**Fix:** rename "Morning Fixed-Level PCR" → "Opening 09:15-09:20 PCR" and
update the Interpretation to spell out *what* window it covers.

### 2. The new V2 `pcr_value` / `morning_pcr_value` are not surfaced here

The new `RedBarV2DirectionDecision` carries `pcr_value` and `morning_pcr_value`
(stored in `process_evidence` rows when the V2 strategy runs). The page
**does not show these** even though they are the V2-aware, decision-time
PCR numbers. Without them, the page shows the "research PCR" but not the
"strategy PCR" the V2 decision actually consumed.

**Fix:** add a new row "V2 Strategy PCR (current)" and "V2 Strategy PCR (morning)"
to the Market Direction Summary, populated from
`process_evidence` for the active run_id (the same source the V2 strategy uses).
Add a "PCR shift (current - morning)" delta row that shows whether the
positioning has rotated since the open.

### 3. PCR freshness window mismatch

`MarketTrendResearchPolicy.maximum_source_age_seconds` is the freshness threshold.
If the data is older than that, the row says "STALE". But the user has no
visibility into *how stale* (3 min vs 30 min). The page silently drops the
direction from the FRESH-state but the user can't tell why.

**Fix:** add a small caption under the PCR rows: "FRESH = within
N seconds; STALE = older than that. The value is still shown so you can
judge." Or render the row with an explicit "Age: 4m12s" tooltip.

### 4. The Combined Index PCR is one number, no breakdown

The "Combined Index PCR" row shows the weighted aggregate with a one-line
"agreement; coverage%". The user can't see *which* underlyings contributed
the most weight, or which one is dragging the average.

**Fix:** in the expander under the table, render
`combined.components` as a small table: name, weight, PCR, direction.
Already computed in the fragment but not exposed.

### 5. The PCR CE/PE preference row hides the underlying reason

The "PCR research CE/PE preference" row shows `BUY CE` / `BUY PE` / `WAIT`
and an interpretation string, but doesn't say *which* PCR signal drove
the decision (morning, current, combined?). When the answer is "WAIT",
the user can't tell whether the morning or the current PCR disagreed.

**Fix:** show the contributing direction per source:
- Morning: BULLISH
- Current: BEARISH
- Combined: NEUTRAL
- Research verdict: WAIT (conflicting signals)
That way the user knows which sub-signal to wait for.

### 6. The page is read-only — that's correct, but the caption could be louder

The current caption is:
> Read-only summary of persisted research. Detailed evidence remains
> inside the two tabs below; this summary has no trading authority.

This is good but lives at the bottom. A trader who skims only the table
might miss it.

**Fix:** add a top-of-page tag: `OBSERVATION ONLY — NO TRADING AUTHORITY`
next to the "## Market Direction Summary" header. Same as the audit row
relabel we did in the V2 lifecycle page.

### 7. No "previous-day comparison"

A PCR of 1.10 means nothing without yesterday's. The same row says
"Current NIFTY option positioning" but doesn't say "vs yesterday's close
0.95" or "vs 5-day average 1.05".

**Fix:** in the expander, render:
- Previous-day closing PCR
- 5-day rolling mean PCR
- 20-day rolling mean PCR
- A sparkline of the last 20 5m PCR values (if `st.line_chart` works on it)

### 8. The new audit row `check:pcr_informational` is in `process_evidence`
but no UI surface

We added it on the V2 lifecycle page (good). But the Trade Evidence page
is the *first* page a trader opens in the morning to decide "is today
trending bullish or bearish" — and the audit row doesn't appear here.
A trader checking this page at 9:25 wants to see the V2 strategy's PCR
context too, not just the research PCR.

**Fix:** add a small panel "Red Bar V2 strategy PCR context" that pulls
the latest `process_evidence` rows for the active run_id where
`step_name='check:pcr_informational'`. Show:
- current pcr_value
- morning pcr_value
- shift (current - morning)
- interpretation (the artifacts_json blob from the audit row)

## Suggested implementation order

1. **Renames** (1, 6) — 5 minutes, no behavior change
2. **Surface V2 PCR** (2, 8) — single helper that reads
   `process_evidence`; 30 min including tests
3. **Breakdown expander for Combined PCR** (4) — already in `combined.components`;
   15 min
4. **Age tooltip on STALE** (3) — 10 min
5. **Verdict reason breakdown** (5) — 15 min
6. **Historical comparison** (7) — 45 min, needs to pull 5d/20d rolling
   from `market_trend_research_pcr_5m_history`

## What is *not* a gap

- The page does not need to be writable. It is correctly read-only.
- The page does not need to call the bridge. The bridge is for *remote*
  validation; this page is for *live local* viewing.
- We should not change the verdict logic. The trader still gets `BUY CE / BUY PE / WAIT`
  as before — we're just adding transparency about *why*.

## Open questions for you

1. Is "OBSERVATION ONLY — NO TRADING AUTHORITY" the right tag wording, or do
   you prefer something shorter like "READ-ONLY"?
2. For (7), the historical comparison — do you want 5d/20d rolling,
   or a different window?
3. For (8), is the "active run_id" always known at the moment this page
   renders, or do we need to show "no run_id set" gracefully?
