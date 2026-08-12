# RB-0.7.4.1 Dual Market Data Collector

This release keeps all three option-data protections active:

1. Continuous online collector
2. Signal-triggered fallback capture
3. Offline / EOD collector

No Red Bar trading rule is changed.

## Continuous online collector

During regular weekday market hours (09:15–15:30 IST), the standalone
collector stores one option-chain history snapshot per minute by default.

Each snapshot contains:
- expiry
- spot / ATM strike
- Call OI / Put OI
- PCR
- change in OI
- Call Wall / Put Wall
- Max Pain
- ATM IV
- ATM Delta / Gamma / Theta / Vega
- raw option-chain CSV path

History is stored in:
- SQLite: `option_chain_snapshot_history`
- CSV: `artifacts/red_bar/options/history/...`

Duplicate collection inside the same minute is automatically collapsed by a
unique snapshot key.

## Signal linking

When a confirmed signal exists, the collector searches for the nearest
ONLINE snapshot at or before entry. If it is within 120 seconds, that snapshot
is linked to the signal as `PRE_ENTRY` and becomes authoritative options
context for the Feature Store.

This is preferable to waiting for an API call after the signal because the
snapshot already existed before the entry.

## Signal-triggered fallback

RB-0.7.4 signal-triggered capture remains enabled inside Live Trading. If the
continuous collector missed the pre-entry window, Live Trading can still
attempt its existing immediate capture.

The live page is not given additional collector controls.

## Offline / EOD service

Outside market hours, the standalone collector runs the offline path and
stores an EOD snapshot. The collector persists status in
`market_collector_status`.

The offline collector enriches/backfills available data; it does not overwrite
an authoritative pre-entry signal snapshot.

Historical/external option-context CSV import remains available under
Intelligence for data that cannot be reconstructed from a current live chain.

## Running the two services

Terminal 1 — Red Bar Lab:

```powershell
.\run_red_bar.ps1
```

Terminal 2 — Dual Market Data Collector:

```powershell
$env:UPSTOX_ACCESS_TOKEN="your-token"
.\run_market_collector.ps1
```

Defaults:
- Underlying: NIFTY 50
- Interval: 60 seconds
- Mode: auto

Examples:

```powershell
.\run_market_collector.ps1 -Underlying "BANK NIFTY"
.\run_market_collector.ps1 -IntervalSeconds 60 -Mode online
.\run_market_collector.ps1 -Mode offline
```

Auto mode:
- Market hours → ONLINE collector
- Outside market hours → OFFLINE/EOD collector

The minimum continuous interval is intentionally 60 seconds.

## Intelligence UI

Intelligence now shows:
- Collector clock mode
- Collector health/status
- Last collector mode
- Last snapshot ID
- Manual Online Tick
- Manual Offline/EOD Tick
- Recent option-chain snapshot history
- Existing Options Context
- Feature Store health

## New tables

- `option_chain_snapshot_history`
- `signal_option_snapshot_links`
- `market_collector_status`

Existing `option_context_snapshots` remains the signal-linked feature table.

## Safety

The continuous collector is independent from Streamlit. If it fails, Live
Trading continues. If Live Trading fails, the standalone collector can
continue collecting market data.

RB-0.7.5 can now focus on interpreting PCR/OI/Greeks instead of acquiring data.
