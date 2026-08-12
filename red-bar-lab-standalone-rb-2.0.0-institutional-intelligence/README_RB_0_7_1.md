# RB-0.7.1 Market Context Engine — Historical Context Collector

Layer 2 begins here.

This release enriches every confirmed Red Bar signal with market context that
was known at the time of entry. It does not change entries, exits, trade
ranking, or signal quality.

Collected price/session context:
- session open
- previous close / high / low
- gap points and gap %
- minutes from market open
- price distance from session open
- session high / low / range up to entry
- entry position inside the session range
- distance to previous-day high / low
- completed 15-minute opening range and entry position relative to it

Collected trend/volatility context:
- ATR(14) on completed 5-minute candles
- EMA9 and EMA21 on completed 5-minute candles
- UPTREND / DOWNTREND / RANGE classification
- 30-minute realized one-minute volatility

Look-ahead protection:
- current-day context uses only candles at or before signal entry
- the opening range is unavailable before 09:30
- ATR and EMA use only completed five-minute bars

Storage:
- SQLite: `market_context_snapshots`
- CSV: `artifacts/red_bar/context/<instrument>/`

The RB-0.7.0 Intelligence Dataset automatically includes these context fields
when snapshots are available.

Next:
- RB-0.7.2 Volume & Structure Context
- RB-0.7.3 Options Context Collector
