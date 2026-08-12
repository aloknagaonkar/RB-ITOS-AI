# RB-0.7.4.10 Paper Automation Observability & Diagnostics

RB-0.7.4.10 makes automatic paper execution observable and self-diagnosing.

The main question this release answers is:

> Why did the dashboard show a valid CE/PE recommendation but no automatic
> paper trade?

## Important behavior correction

Previous automatic paper execution filtered confirmed signals with:

`state == ACTIVE`

This could hide a confirmed signal from the paper monitor after the underlying
Red Bar lifecycle had already transitioned the signal to `CLOSED`.

RB-0.7.4.10 removes the ACTIVE-only execution filter.

Automatic paper execution now considers a signal when it has:

- signal_id
- confirmation_timestamp
- BULLISH or BEARISH direction

The actual automatic execution gates are then evaluated explicitly:

- market-entry hours
- signal freshness
- duplicate-order protection
- CE/PE candidate availability
- minimum candidate score
- usable option entry quote
- virtual capital / lot-size validation

A confirmed `CLOSED` Red Bar signal can therefore still be paper-executed if
it is fresh and has not already been executed.

This does NOT mean old signals are traded.

## Freshness remains mandatory

Default automatic-entry freshness:

`180 seconds`

Example:

- signal confirmed at 10:45
- paper monitor starts at 11:00
- signal age = 900 seconds
- result = SKIP
- reason = `STALE_SIGNAL age=900s > max=180s`

The dashboard can continue to display that older signal for analysis, but the
paper engine will not enter it late.

## Paper Monitor heartbeat

New persistent table:

`paper_monitor_status`

The background paper monitor writes a heartbeat every cycle.

Paper Trading now shows:

- Background Monitor: RUNNING / OFFLINE / STALE
- heartbeat age
- current monitor state
- orders opened
- orders closed
- last decision
- last scan
- last signal
- last reason
- last error

A heartbeat older than 20 seconds is shown as OFFLINE / STALE.

With the default paper-monitor interval of 5 seconds, a healthy monitor should
normally show a heartbeat only a few seconds old.

## Automatic execution eligibility

The Current Red Bar Decision section now also shows:

- confirmed = YES/NO
- signal age in seconds
- freshness gate PASS/FAIL
- current Red Bar signal state
- whether the signal was already paper-executed
- monitor result

This makes it clear that:

`Trader Recommendation = READY`

does not by itself mean:

`Automatic entry will be opened now`

A historical/stale recommendation can remain useful for analysis while failing
the freshness gate.

## Per-signal diagnostic audit

New table:

`paper_signal_diagnostics`

Every automatic execution scan can record:

- scan ID
- signal ID
- signal lifecycle state
- direction
- confirmation timestamp
- signal age
- market-hours gate
- freshness gate
- duplicate gate
- candidate availability
- best candidate
- best score
- configured minimum score
- score gate
- final decision
- exact reason

Paper Trading displays this under:

`Why Was / Wasn't a Paper Trade Executed?`

Typical reasons include:

- `OUTSIDE_AUTOMATIC_ENTRY_HOURS`
- `STALE_SIGNAL`
- `ALREADY_EXECUTED_FOR_SIGNAL`
- `WAIT_RECHECK_THROTTLED`
- `NO_ELIGIBLE_CE_PE_CANDIDATE`
- `SCORE_BELOW_THRESHOLD`
- `PAPER_ORDER_OPENED`
- an explicit ERROR message

## Execution state audit

The existing execution timeline remains.

A stale signal can now also produce:

`SKIPPED_STALE`

This complements the more detailed diagnostic table.

## How to validate during market hours

Start the complete platform:

```powershell
$env:UPSTOX_ACCESS_TOKEN="your-token"
.\start_red_bar_platform.ps1 -Underlying "NIFTY 50"
```

Then open Paper Trading.

First check:

- Background Monitor = RUNNING
- Heartbeat = approximately 0-20 seconds
- Current State = WAITING_FOR_SIGNAL or MONITORING_POSITION

When a new confirmed signal appears, inspect Automatic Execution Eligibility.

For automatic entry the expected gates are:

- Confirmed = YES
- Signal Age <= 180s
- Freshness Gate = PASS
- Already Executed = NO
- candidate score >= Minimum Score

The diagnostic table should then show either:

`Decision = OPENED`

or a precise reason for the skip.

## Safety

Paper execution remains virtual.

Live broker execution remains HARD DISABLED.

`ZerodhaLiveExecutionProvider.LIVE_EXECUTION_ENABLED = False`

No live broker order endpoint is enabled.

## Validation

RB-0.7.4.10 includes regression coverage for:

- confirmed CLOSED signal eligibility
- paper-monitor status persistence
- per-signal diagnostic persistence
- observability UI sections
- all previous Red Bar tests

Next planned stage after successful live-market paper validation:

`RB-0.8.0 — AI Learning Engine`
