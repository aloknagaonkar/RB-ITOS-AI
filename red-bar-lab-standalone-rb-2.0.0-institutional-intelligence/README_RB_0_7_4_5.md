# RB-0.7.4.5 Paper Trading / Demo Execution Engine

RB-0.7.4.5 adds broker-agnostic virtual option execution with Zerodha as the
first market-data provider.

## Safety contract

Execution mode is hard-locked to:

`PAPER`

The Zerodha client in this release implements:
- login URL
- request-token to access-token exchange
- profile validation
- NFO instrument master
- full quotes / depth
- LTP
- historical option candles

It intentionally implements NO broker order-placement, order-modification, or
order-cancellation methods.

All paper orders are created and stored locally in Red Bar.

## New workspace

Sidebar:

`Paper Trading`

The workspace shows:
- Execution Mode = PAPER
- Market Data = ZERODHA
- Live Orders = DISABLED
- Zerodha login/token tools
- Virtual Portfolio
- Red Bar direction / CE-PE candidate selection
- nearest option strikes
- LTP, volume, OI, bid/ask and lot size
- virtual entry
- open virtual positions
- live paper P&L
- MFE / MAE
- virtual exit
- actual selected option candles
- EMA9 / EMA21 / VWAP on the option itself
- closed paper positions

## CE / PE behavior

Until the AI Recommendation Engine is implemented:

- BULLISH Red Bar direction -> CE candidates
- BEARISH Red Bar direction -> PE candidates

The nearest-expiry option master is used and the nearest strikes to the
underlying spot are shortlisted.

This is a candidate-selection workflow, not an AI strike recommendation yet.

## Virtual fills

For a paper BUY:
1. Use best ask from Zerodha market depth when available.
2. Otherwise simulate a small configurable slippage above LTP.

For a paper SELL/exit:
1. Use best bid when available.
2. Otherwise simulate slippage below LTP.

This is more conservative than simply assuming every virtual order fills at
the displayed LTP.

## Virtual portfolio

Default paper capital:

`₹100,000`

Tracked:
- available capital
- deployed capital
- realized P&L
- unrealized P&L
- net P&L
- open positions
- closed positions

Quantity must be a multiple of the instrument's current Zerodha lot size from
the instrument master.

## Option candle intelligence foundation

The selected CE/PE contract can load its real Zerodha historical minute
candles including:
- OHLC
- volume
- OI

Red Bar derives:
- EMA9
- EMA21
- VWAP

These are displayed separately from the underlying NIFTY/BANKNIFTY candles.
This becomes the foundation for future CE/PE Candle Intelligence.

## Persistent paper execution tables

- `paper_execution_accounts`
- `paper_execution_orders`
- `paper_execution_marks`

Every virtual position stores its signal link, exact contract, expiry, lot
size, quantity, entry, current mark, exit, P&L, MFE and MAE.

## Standalone paper monitor

Run separately:

```powershell
$env:ZERODHA_API_KEY="..."
$env:ZERODHA_ACCESS_TOKEN="..."
.\run_paper_monitor.ps1
```

Default refresh interval:

`5 seconds`

It refreshes only open Red Bar virtual positions using Zerodha market quotes.
It never sends broker orders.

## Unified launcher

If these are configured:

```powershell
$env:UPSTOX_ACCESS_TOKEN="..."
$env:ZERODHA_API_KEY="..."
$env:ZERODHA_ACCESS_TOKEN="..."
```

then:

```powershell
.\start_red_bar_platform.ps1
```

starts:
1. Upstox Dual Market Collector
2. Zerodha Paper Position Monitor
3. Red Bar Streamlit UI

If Zerodha environment variables are absent, Red Bar and the Upstox collector
still start and the paper monitor is skipped.

## Monday workflow

1. Refresh the Upstox and Zerodha sessions.
2. Start the platform.
3. Open Paper Trading.
4. Validate Zerodha connection.
5. Wait for a confirmed Red Bar signal or select direction manually.
6. Load CE/PE candidates.
7. Inspect quote, liquidity and the option candle.
8. Open a virtual paper position.
9. Let the paper monitor mark P&L.
10. Close virtually and review the journal.

## What this release does NOT do

- No live Zerodha order
- No live Upstox order
- No AI CE/PE recommendation yet
- No AI strike ranking yet
- No autonomous entry
- No autonomous exit

Those remain later releases after paper-validation data has been collected.

## Next

RB-0.8.0 — AI Learning Engine

Then:
- Historical Similarity
- Options + CE/PE Candle Intelligence
- Recommendation Validation Gate
- Exact CE/PE and strike recommendation
