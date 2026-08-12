# RB-0.7.4.8 Paper Trading Command Center

RB-0.7.4.8 turns the Paper Trading workspace into the command-center layout
planned before AI development.

It also fixes the RB-0.7.4.7 runtime error:

`Upstox market intelligence unavailable: name 'UnifiedUpstoxMarketIntelligenceService' is not defined`

The error was caused by the Paper Trading workspace using the new Upstox
intelligence classes without importing them into `workspace.py`.

## Runtime fix

The workspace now explicitly imports:

- `UnifiedUpstoxMarketIntelligenceService`
- `UpstoxPaperMarketAdapter`

This is covered by UI regression tests.

## Paper Trading Command Center

The Paper Trading page is now organized as one scrollable command center.

### Command Status

Shows:

- Market OPEN / CLOSED
- Execution = PAPER
- Market Data = UPSTOX
- Paper Automation = ENABLED
- Live Orders = HARD DISABLED
- Kill Switch = ACTIVE

### Market Health & Paper Account

Market:

- Spot
- PCR (OI)
- Call Wall
- Put Wall
- Max Pain
- Current expiry
- Upstox snapshot time

Paper account:

- Available virtual capital
- Deployed capital
- Net paper P&L
- Open / closed positions

### Current Red Bar Decision

Shows the latest confirmed Red Bar signal:

- Signal ID
- BULLISH / BEARISH direction
- LOOK FOR CE / LOOK FOR PE
- signal state
- confirmation time

No AI label is used in this release.

### Top CE / PE Candidates

A manual refresh ranks current option contracts.

The table includes:

- rank
- option symbol
- CE / PE
- strike
- rule score
- LTP
- bid
- ask
- spread score
- liquidity score
- volume score
- OI score
- VWAP score
- EMA score
- momentum score
- Delta
- Gamma
- IV
- Theta
- Vega
- PAPER BUY / WAIT decision

The page highlights the best paper candidate.

This remains a RULE-BASED PAPER RECOMMENDATION.

### Paper Execution

Controls:

- minimum paper score
- lots
- Run Automatic Paper Cycle Now
- Refresh Open Positions
- automatic SL / Target / 15:25 EOD policy

### Manual Paper Entry

The highest-ranked contracts remain manually selectable for validation.

Manual paper entry:

- uses Upstox quote/depth
- creates a Red Bar virtual order only
- does not transmit a broker order

### Open Paper Position

Shows precise:

- signal
- option
- type
- strike
- entry time
- entry price
- current price
- points
- P&L
- MFE
- MAE
- stop
- target
- status

A selected open paper position can be closed manually.

### Selected Option Candle

For the open CE/PE contract the page shows:

- option close
- VWAP
- EMA9
- EMA21
- volume
- intraday line chart

This uses the actual selected option contract rather than only the NIFTY
underlying.

### Why This Option?

The evidence panel separates the current rule score into:

- spread
- liquidity
- volume
- OI
- VWAP
- EMA
- momentum

Greeks are shown separately as INFORMATIONAL in RB-0.7.4.8:

- Delta
- Gamma
- IV
- Theta
- Vega

They are not silently added to the current rule score.

### Execution Timeline

Displays the persisted execution-state audit:

- SIGNAL_CONFIRMED
- CANDIDATE_SELECTION
- WAITING_FOR_ENTRY
- OPEN
- MONITORING
- EXIT_TRIGGERED
- CLOSED
- NO_CANDIDATE
- ERROR

### Paper Trade Journal & Statistics

For completed option paper trades:

- closed trades
- winners
- losers
- win rate
- net realized P&L
- profit factor

Journal columns include:

- signal
- option
- CE / PE
- strike
- entry / exit time
- entry / exit price
- quantity
- P&L
- MFE
- MAE
- exit reason

### AI Status

The page explicitly states that AI Learning has not started yet.

RB-0.7.4.8 organizes the evidence needed by RB-0.8:

- Red Bar signal
- market context
- candidate ranking
- Greeks
- CE/PE candle
- entry
- monitoring path
- exit
- MFE / MAE
- outcome

## Safety

Live execution remains disabled.

`ZerodhaLiveExecutionProvider.LIVE_EXECUTION_ENABLED = False`

No live broker order API is enabled by this release.

## Validation

The full test suite must pass before packaging.

Next planned release:

`RB-0.8.0 — AI Learning Engine`
