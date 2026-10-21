# BULLISH_GAP2_FULL_WMA2 promotion: component inventory

Routing strategy ID remains HILEGA_V2_ALIGNMENT_DUAL_EXIT for compatibility with existing downstream journals. Policy ID is BULLISH_GAP2_FULL_WMA2; version is bullish-gap2-full-wma2-1.0.0. Existing historical records are not rewritten.

| Component | Existing dependency | Implemented change |
|---|---|---|
| Live coordinator | Original minute confirmation gate | Shared completed5m combined gate; incremental continuous price EMA10; candidate/follow-up lifecycle and bullish 2/2 checks |
| Replay engine used by UI | Legacy alignment replay | Separate combined replay using the SAME advance_boundary function as live; separate artifact directory and source fingerprint |
| Frozen research scripts | Original alignment replay source | Original module remains unchanged, allowing old baselines and research to reproduce |
| Decision audit journal | Original checks and accepted events | New version/policy metadata, original setup time, signal/follow-up evidence, price EMA frame and pending reference |
| Audit inspection | Minute persistence and ten-minute-window explanation | New policy-specific inspector; recorded strength/gap, EMA position/slope, RSI continuation, candle colour, midpoint/price/fresh routes, EMA touch and full WMA magnitude |
| Historical/live audit projection | Discarded strategy_steps in report conversion | Carries authoritative steps and policy events into the decision table; five-minute OHLC for new-policy rows |
| Decision table frontend | Original inspection label and no policy-event list | Displays policy-event table and recorded rule inspection; accepted execution events remain separate |
| Confirmation audit panel | Minute-stage filter and persistence column | Includes combined-five-minute stage; persistence explicitly NOT REQUIRED for new policy |
| Independent five-contract option shadow | Confirmed entry/exit event types | Existing event contracts retained; new confirmed timestamp/underlying price used; versioned audit metadata; old-version option restore excluded |
| Policy publisher / Top 5 observer | One-minute price history and confirmed entries | Non-trading minute-price audit stage maintains velocity inputs; carries source policy/version into Top 5 frames |
| Strike ranking | Version-bound approved strike policy | Ranking formula, quote/depth/expiry checks remain. Old approved strike policies are NOT silently reapproved for new version; require explicit review if ranked sandbox mode is used |
| Sandbox event bridge | Accepted entry and exit names | Names/routing ID retained; intent carries policy ID and strategy version. Waiting/qualification events do NOT become BUY intents |
| Sandbox basket worker | Armed control and source intents | New arm stores policy/version; promoted-policy BUY requires matching arm/source version. EXIT reconciliation is not blocked by this new-entry guard |
| Sandbox positions/pending-order UI | Fill ledger and broker order state | Existing ledger remains authoritative; no journal rewrite or acceptance-as-fill changes |
| Manual exit/reset | Cleared original pending dictionary | Also clears follow-up reference and price permission, preserving warmed EMA/indicator state |
| Recovery | Replayed minutes and option audit restore | Reconstructs new gate/EMA state from exact candles; restore only matching policy version; installer requires flat sandbox and stopped services |
| VWAP / PCR / bias | Observation data | No entry filters added; existing observations continue |
| Readiness / expiry / contracts / risk | Existing strategy routing ID | Routing ID retained. Existing freshness, quote-quality, fill/reconciliation, manual and cutoff safeguards remain |

## Exact rules

- Completed five-minute canonical or fresh alternative setup. No provisional minute-gap setup veto.
- Qualified signal: directional RSI9/EMA3(RSI9)/WMA21(RSI9) ordering, directional WMA strength >=0.75, positive gap expanding versus previous completed5m, correct side of price EMA10, directional EMA10 slope, directional candle colour and RSI rising >40 bullish / falling <60 bearish.
- Bullish qualified signal also requires EMA3(RSI9)-WMA21(RSI9)>=2.
- No entry on signal candle. Follow-up requires directional candle colour and RSI direction, plus price beyond signal close OR midpoint OR fresh strength/positive-expanding-gap checks.
- Bullish entry also requires entry WMA minus WMA immediately BEFORE qualified signal >=2.
- Failed follow-up retains original reference only if current candle touches EMA10; otherwise discard reference and seek fresh qualification, including on the failed candle itself.
- Underlying candidate does not expire by time. Fully qualifying opposite signal may replace the watch; arms alone cannot.
- WMA direction lock and its exceptions disabled. No bearish EMA30 substitution.
- Existing dual exits and 14:55 cutoff retained. No extra EMA10 exits.

## Validation status

Source changes and test/validation programs are prepared. No Python, pytest or frontend build was run in the assistant environment, per the user's instruction. Do not describe the package as deployment-validated until VM checks pass. The installer refuses activation without eleven October-session research and live/replay parity reports for this exact policy implementation.

## Scope limits

This promotes underlying signal generation, not live broker execution. Option selection/ranking remains an independent consumer with its own quote/velocity/approval checks and can still decline a valid underlying signal. Option P&L/fills cannot be inferred from NIFTY points. A prior-version ranked-strike approval must be reviewed rather than rewritten. Do not switch with open or unresolved sandbox exposure.
