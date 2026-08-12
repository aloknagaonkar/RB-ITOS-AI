# RB-0.7.4.6 Execution Foundation & Paper Automation

This release automates the Red Bar paper-execution lifecycle while building
the interfaces required for future Zerodha live execution.

## Safety

LIVE EXECUTION REMAINS DISABLED.

`ZerodhaLiveExecutionProvider.LIVE_EXECUTION_ENABLED = False`

The future live provider contains no Zerodha order-submission call. Its
`submit()` method always raises an error in RB-0.7.4.6.

The live kill-switch foundation is ACTIVE by default.

## Automatic paper lifecycle

During regular automatic-entry hours, the standalone paper monitor now:

1. Finds fresh confirmed ACTIVE Red Bar signals.
2. Maps:
   - BULLISH -> CE candidates
   - BEARISH -> PE candidates
3. Loads the nearest-expiry Zerodha NFO contracts.
4. Scores candidate strikes.
5. Opens one virtual paper position when the best score passes the threshold.
6. Marks the open position from live Zerodha quotes.
7. Calculates virtual P&L, MFE and MAE.
8. Automatically exits on:
   - paper stop loss
   - paper target
   - EOD exit
9. Persists the complete execution audit trail.

No broker order is sent.

## Fresh-signal protection

Automatic entry defaults to a maximum signal age of 180 seconds.

If the paper monitor is started late in the day, old confirmed signals are not
automatically converted into new virtual positions.

Manual paper controls remain available in the UI for research/testing.

## Market-hours protection

Automatic entries are accepted only during the paper-entry session:

09:15 IST <= time < 15:25 IST

Outside that window the service can still monitor/close an already-open paper
position, but it does not create a new automatic entry.

## Candidate scoring

This is explicitly a RULE-BASED PAPER score, not an AI recommendation.

The published score is normalized to 0-100 and uses only data available from
the implemented Zerodha connector:

- bid/ask spread
- bid/ask available quantity / liquidity
- traded volume
- OI
- selected option close vs VWAP
- selected option EMA9 vs EMA21
- short-term option-price momentum

No Greeks are invented or approximated in this layer.

Upstox Options Intelligence will later supply PCR/Greeks/IV/context to the AI
fusion layer.

Default minimum automatic paper score:

65 / 100

## API-traffic controls

The Zerodha NFO instrument master is cached in-process.

If a new signal receives a WAIT decision, candidate re-evaluation is throttled
(default 30 seconds) while live position marking can continue at the faster
paper-monitor interval.

## Paper execution risk policy

The current automated virtual-position defaults are paper-testing rules only:

- Stop: 15% below simulated option entry
- Target: 25% above simulated option entry
- EOD exit: 15:25 IST

These are not claimed to be optimal trading rules. Their purpose is to create a
consistent, measurable paper lifecycle for later AI learning and validation.

## Idempotency

One automatic paper execution is allowed per:

`signal_id + paper account`

A database unique index and execution check prevent duplicate virtual entries
from repeated monitor cycles.

## Execution states

The audit trail can include:

- SIGNAL_CONFIRMED
- CANDIDATE_SELECTION
- WAITING_FOR_ENTRY
- OPEN
- MONITORING
- EXIT_TRIGGERED
- CLOSED
- NO_CANDIDATE
- ERROR

Tables:

- `execution_state_events`
- `paper_candidate_decisions`
- existing `paper_execution_orders`
- existing `paper_execution_marks`

## Live-ready execution abstraction

New interface foundation:

- `ExecutionIntent`
- `ExecutionProvider`
- `ExecutionSafetyState`
- `ZerodhaLiveExecutionProvider`

Future live safety state already models:

- live execution enable flag
- kill switch
- market-hours gate
- instrument verification
- quantity verification
- duplicate-order protection

Even if all other gates are true, RB-0.7.4.6 cannot allow live execution
because `LIVE_EXECUTION_ENABLED` is false.

## Paper Trading UI

The Paper Trading page now shows:

- PAPER mode
- Zerodha market data
- Paper Automation enabled
- Live Orders HARD DISABLED
- live-foundation kill-switch state
- automatic paper configuration
- Run Automatic Paper Cycle Now
- rule-based paper recommendations
- manual CE/PE inspection/trading controls
- open positions
- actual CE/PE candles
- execution-state audit
- closed positions

## Standalone automation

Use:

```powershell
$env:ZERODHA_API_KEY="..."
$env:ZERODHA_ACCESS_TOKEN="..."
.\run_paper_monitor.ps1 -Underlying "NIFTY 50" -Lots 1 -MinimumScore 65
```

The default quote/monitor interval remains 5 seconds.

The unified launcher passes its selected underlying to the paper monitor:

```powershell
.\start_red_bar_platform.ps1 -Underlying "NIFTY 50"
```

## Trading logic

No existing Red Bar underlying signal/entry/exit/backtest rules are modified by
this release.

The automated CE/PE paper layer is separate and exists to generate realistic,
auditable option-execution evidence.

## Next release

RB-0.8.0 — AI Learning Engine

It will learn from completed Red Bar and paper-option trades without making
live broker orders.
