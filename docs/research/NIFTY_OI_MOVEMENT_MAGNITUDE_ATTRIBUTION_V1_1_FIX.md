# NIFTY OI Movement Magnitude Attribution V1.1 schema fix

The V1 run correctly loaded:
- 90 sessions
- 6,660 checkpoints
- forward NIFTY movement labels

but every OI sample count was zero.

Root cause:
the canonical enriched row schema does not expose the 5m/10m/15m OI fields as
top-level `imbalance_5m`, `imbalance_10m`, etc.

The actual enriched schema stores them under:

`moving_horizons["5m"]`
`moving_horizons["10m"]`
`moving_horizons["15m"]`

with keys:
- `ce_delta`
- `pe_delta`
- `imbalance`
- `current_pcr`
- `prior_pcr`
- `pcr_change`

The enrichment also exposes convenient 5m aliases:
- `m_ce_delta`
- `m_pe_delta`
- `m_pcr`
- `m_pcr_change`

V1.1 fixes extraction to use the nested canonical enriched schema and retains
backward-compatible flat/5m alias handling.

It also adds an OI coverage gate so a future run cannot report PASS with zero
5m OI samples.

Expected after the fix:
- `oi_coverage_by_lookback["5m"]` > 0
- 10m and 15m coverage also > 0 after their natural early-session unavailable rows
- attribution rows contain numeric minima/percentiles instead of all null values.

No research methodology changes:
- same 90 sessions
- same 6,660 checkpoints
- same exact 5m future checkpoint movement definition
- no stop-loss / P&L / trade logic
