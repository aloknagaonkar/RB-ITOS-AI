# RB-0.7.4.2 Intelligence Pipeline Orchestrator

This release changes Intelligence from a manual collection workflow into an
automatic, fault-isolated data pipeline.

No Red Bar signal, entry, exit, actionable-model, benchmark, or backtest rule
is changed.

## Automatic pipeline

When Live Trading refreshes and confirmed signals exist:

1. Red Bar trading logic completes normally.
2. Existing signal-triggered Options Context fallback remains active.
3. Market Context is created automatically if missing.
4. Volume & Structure Context is created automatically if missing.
5. The nearest authoritative PRE_ENTRY option snapshot is linked if available.
6. Feature Store readiness is evaluated.
7. CORE and HYBRID eligibility are persisted.

A failure in any enrichment stage is isolated and does not interrupt Live
Trading.

## Independent collector integration

The standalone Dual Market Data Collector now also runs the pipeline
orchestrator after each online collection tick.

This means:
- Streamlit does not need to be on the Intelligence page.
- The collector can link pre-entry option snapshots automatically.
- Context completeness is continually evaluated.
- EOD validation is performed after the EOD collector completes.

## Feature profiles

### CORE
Requires:
- confirmed Red Bar signal
- Market Context
- Volume & Structure Context

Options data is not required.

### HYBRID
Requires:
- all CORE context
- entry-aligned Options Context

This lets older historical trades remain useful for CORE intelligence even
when historical options snapshots are unavailable.

## EOD validation

After an eligible EOD collection, the orchestrator records:
- confirmed signal count
- CORE eligible count
- HYBRID eligible count
- CORE completeness %
- HYBRID completeness %
- COMPLETE / INCOMPLETE state

Table:
`eod_pipeline_validation`

## New operational tables

- `signal_pipeline_status`
- `intelligence_pipeline_run_status`
- `eod_pipeline_validation`

## Intelligence UI

The top of Intelligence is now the automatic operations view:
- Pipeline status
- CORE eligibility
- HYBRID eligibility
- Missing Options count
- Per-signal readiness
- EOD validation

The existing build/capture buttons are now presented under:

`Maintenance / Backfill`

They are intended for:
- rebuilding history
- repairing missing records
- testing
- historical backfill

They are not required for normal live operation.

## Collector session safety

Auto collector mode now distinguishes:
- PREOPEN
- OPEN
- POSTCLOSE
- WEEKEND

It does not perform an EOD request during pre-open or weekends.

On weekday POSTCLOSE, automatic EOD collection is performed only when an
ONLINE snapshot exists for that trading date. This also protects normal
holidays/no-session days from being treated as a trading day.

Manual `-Mode offline` remains available when a forced offline snapshot is
required.

## One-command platform start

Instead of manually starting two windows:

```powershell
$env:UPSTOX_ACCESS_TOKEN="your-token"
.\start_red_bar_platform.ps1
```

This starts:
- Dual Market Data Collector in a separate PowerShell window
- Red Bar Lab UI in the current PowerShell window

The collector defaults to a 60-second interval.

You can still run services separately:

```powershell
.\run_red_bar.ps1
.\run_market_collector.ps1
```

## Daily manual work

Normal operation should require only:
1. Set/refresh the Upstox access token.
2. Start the platform.

Market Context, Volume/Structure Context, options linkage, Feature Store
eligibility, and EOD validation are automatic.

Next planned release:
RB-0.7.4.3 — Historical Backfill Manager.
