# RB-0.6.8 Signal Lifecycle Stabilization

This release stabilizes the live Red Bar signal → trade relationship.

## Canonical Signal ID
Live signals and paper trades now use the same canonical `RB-*` signal ID.
Existing legacy `SIG-*` paper-trade rows are relinked to the canonical signal
when the live/historical signal set is refreshed.

## Automatic Live Paper Trades
The Live monitor refreshes paper-trade models automatically for confirmed
signals. Users no longer need to open the Trades tab to keep today's models
updated.

## Correct Intraday Lifecycle
Before the real session end:
- unresolved fixed targets remain `OPEN`;
- unresolved risk/reward models remain `OPEN`;
- unresolved trailing models remain `OPEN`;
- break-even models remain `OPEN` when no exit has occurred;
- EOD Hold stays `OPEN`.

They are no longer incorrectly closed as `EOD` merely because the latest
cached candle is the current last candle.

At/after 15:30 IST, unresolved models finalize using EOD logic.

## Live Target Progress
For every confirmed signal the Live table shows:
- current live points;
- live MFE / MAE;
- 20/30/40/50 targets already reached using best favorable move;
- next target;
- points currently required to reach the next target;
- open/closed trade-model counts;
- signal lifecycle.

## Signal Lifecycle
- `ACTIVE`: confirmed signal exists but no linked trade model yet.
- `TRADE_OPEN`: one or more trade models remain open.
- `COMPLETED`: all linked trade models are closed.

## Drill-down
The Live tab includes a Signal Drill-down selector. Selecting a live signal
shows all linked exit-model trades for the same canonical signal ID.

No existing historical candle files or market cache are deleted.
