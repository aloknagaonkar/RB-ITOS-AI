# RB-0.7.4.7 Unified Upstox Market Intelligence

RB-0.7.4.7 makes Upstox the primary market-data backbone for Red Bar paper
trading and the future AI/options intelligence layers.

## Why this release

RB-0.7.4.6 used Zerodha as the paper market-data adapter. That created a second
paid market-data dependency even though Red Bar already collects Upstox
options data.

RB-0.7.4.7 removes that requirement from paper trading.

Paper execution remains entirely virtual inside Red Bar.

## Unified Upstox Market Intelligence Service

New service:

`UnifiedUpstoxMarketIntelligenceService`

It creates a single cached market snapshot containing:

- underlying spot
- expiry
- complete option-chain dataframe
- CE/PE LTP
- volume
- OI
- previous OI
- change in OI
- bid / ask
- bid / ask quantity
- IV
- Delta
- Gamma
- Theta
- Vega
- Probability of Profit when supplied by Upstox
- PCR derived from total OI
- Call Wall
- Put Wall
- Max Pain

The option-chain snapshot cache defaults to 2 seconds so multiple Red Bar
components can share the same market view instead of requesting the same chain
repeatedly.

Option-contract metadata is cached separately for 5 minutes by default.

## Upstox API additions

The internal Upstox client now supports:

- Option Contracts
- Option Greeks for up to 50 instrument keys per request

Existing support remains:

- Put/Call Option Chain
- Intraday candles
- Historical candles
- Historical OI
- Historical Change in OI
- Expiries

The Put/Call Option Chain is used as the primary live options snapshot because
it already carries market data and Greeks together.

The dedicated Option Greeks API remains available for later targeted refreshes.

## Upstox Paper Market Adapter

New adapter:

`UpstoxPaperMarketAdapter`

It maps the unified Upstox data into the read-only interface expected by the
existing Red Bar paper engine.

This means the tested paper execution lifecycle did not need to be rewritten.

The adapter supplies:

- instrument/contract discovery
- lot size
- current underlying spot
- option LTP
- bid / ask
- bid / ask quantity
- volume
- OI
- IV
- Delta
- Gamma
- Theta
- Vega
- option candles

## Paper Trading changes

Paper Trading now shows:

`Market Data = UPSTOX`

The previous Zerodha market-data login requirement has been removed from the
paper workflow.

The existing future Zerodha LIVE execution foundation remains separate and
hard-disabled.

Paper candidate tables can now expose Greeks and IV directly from the Upstox
chain.

## Automated paper monitor

Only this token is required for market data:

```powershell
$env:UPSTOX_ACCESS_TOKEN="your_upstox_token"
```

Run:

```powershell
.\run_paper_monitor.ps1 -Underlying "NIFTY 50"
```

or start the complete platform:

```powershell
.\start_red_bar_platform.ps1 -Underlying "NIFTY 50"
```

The same Upstox access token now powers:

1. continuous options collector
2. intelligence pipeline
3. historical backfill
4. unified market intelligence
5. automated paper execution
6. CE/PE option candles

## Architecture

```text
                     UPSTOX
                       |
         Unified Market Intelligence
                       |
       +---------------+----------------+
       |               |                |
  Options Context  Paper Trading   Future AI
       |               |                |
       +---------------+----------------+
                       |
                 Feature Store
```

Future live execution remains broker-independent:

```text
Recommendation
      |
Execution Manager
      |
 +----+--------------------+
 |                         |
PAPER                  FUTURE LIVE
Red Bar                 Zerodha/Dhan/Upstox
```

## Safety

No live order method was added.

`ZerodhaLiveExecutionProvider.LIVE_EXECUTION_ENABLED` remains `False`.

Paper orders are still local Red Bar records only.

## Next planned stage

RB-0.8.0 — AI Learning Engine

It can now consume one consistent Upstox market/options view including Greeks,
instead of depending on a second market-data broker.
