# RB-0.7.2 Volume & Structure Context

Layer 2 — Market Context Engine, module 2.

This release collects entry-time volume and market-structure features without
changing any Red Bar trading rule or using the new data for decisions yet.

Collected volume context:
- current 1-minute volume
- 20-minute average volume
- relative volume (RVOL)
- short-term volume trend
- price/volume state:
  - bullish accumulation
  - bearish distribution
  - weak rally
  - weak decline
  - neutral

Collected market structure:
- 20-minute range width
- compression ratio
- compression / expansion / range
- bullish / bearish breakout
- breakout strength
- higher-high count
- lower-low count
- bullish structure score
- bearish structure score

All calculations are restricted to candles available at or before the signal
entry timestamp.

Storage:
- SQLite: `volume_structure_snapshots`
- CSV: `artifacts/red_bar/context/<instrument>/volume_structure_<from>_<to>.csv`

RB-0.7.0 Intelligence Dataset now merges:
1. Red Bar entry features
2. RB-0.7.1 price/session/volatility context
3. RB-0.7.2 volume/structure context

Next: RB-0.7.3 Options Context Collector.
