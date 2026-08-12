# RB-0.7.4.4 Operations Center

This is the final infrastructure release before the RB-0.8 AI phase.

The Operations Center is a read-only mission-control workspace. It aggregates
system health and data readiness without changing Red Bar trading rules.

## Workspace

The former Dashboard entry is replaced by:

`Operations Center`

The page is intentionally one scrollable dashboard rather than nested tabs.

## Sections

### Overall Health
- 0–100 operational health score
- HEALTHY / WARNING / CRITICAL state
- running Red Bar version

### Platform Health
- Database
- Dual Options Collector
- Intelligence Pipeline
- Feature Store
- Options Context
- Upstox token availability

Each row shows state and supporting detail.

### Market Operations
- Market phase
- collector status/mode
- last option snapshot
- online snapshot count
- EOD snapshot count
- current expiry

### Intelligence Pipeline
- signals today
- confirmed signals
- Market Context coverage
- Volume/Structure coverage
- Options Context coverage
- CORE readiness
- HYBRID readiness
- pipeline status
- EOD validation status

### AI Readiness
- completed paper-trade samples available for learning
- target training sample count
- readiness percentage
- historical signal count
- Feature Store row count
- historical-options backfill days

Important: AI Readiness is a DATA-VOLUME readiness measure. It is not a claim
of model accuracy or profitability.

### Data Quality
- missing Market Context
- missing Volume/Structure Context
- missing entry-aligned Options Context
- incomplete CORE
- incomplete HYBRID
- duplicate option snapshot detection
- current pipeline partial/error flag

### Performance & Storage
- SQLite database size
- artifacts directory size
- Feature Store row count
- historical-options backfill size in days
- collector heartbeat age
- Streamlit/UI process memory when `psutil` is available

### Today's Timeline
Combines operational events into one chronological view:
- option-chain snapshots
- confirmed Red Bar signals
- paper-trade model closes
- pipeline updates
- EOD validation

## Health score

The health score is an operational score built from:
- Database health
- Collector health
- Pipeline health
- CORE Feature Store completeness
- Data/context completeness

It is NOT a market prediction, trading confidence, or AI confidence score.

## Trading safety

RB-0.7.4.4 does not modify:
- signal detection
- entry rules
- exit rules
- 10 actionable models
- EOD benchmark
- live trade evaluation
- paper-trade evaluation
- backtesting rules
- Feature Store look-ahead protection

## Release checklist

- [x] Operations Center workspace
- [x] Platform Health
- [x] Market Operations
- [x] Intelligence Pipeline
- [x] AI Readiness
- [x] Data Quality Monitor
- [x] Performance / Storage Monitor
- [x] Operational Timeline
- [x] Health Score
- [x] Unit tests
- [x] UI regression tests
- [x] Backward-compatible database reads
- [x] Documentation
- [x] Trading logic unchanged

## Next release

`RB-0.7.4.5 — Paper Trading / Demo Execution`

This will let us validate future CE/PE recommendations against real market data
without placing live broker orders.

After the paper execution layer is stable:

`RB-0.8.0 — AI Learning Engine`
