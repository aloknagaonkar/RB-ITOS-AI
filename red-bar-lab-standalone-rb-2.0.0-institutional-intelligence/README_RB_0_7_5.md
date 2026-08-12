# RB-0.7.5 Trade Lifecycle, Provenance & Stable Navigation

RB-0.7.5 makes every paper trade traceable back to the Red Bar signal that
created it and fixes dashboard navigation so timed/browser refreshes remain on
the selected workspace instead of returning to Operations Center.

## Stable page refresh

The current workspace is stored in the URL query parameter:

`?page=Paper+Trading`

When the browser auto-refreshes, Streamlit reads that value and restores the
same workspace.

This applies to all workspace pages, not just Paper Trading.

## Trade Lifecycle & Provenance

A new Paper Trading section lists every paper execution, both OPEN and CLOSED.

Each trade shows:

- Trade/order ID
- Signal ID
- Signal Type (`level_type`)
- Signal Direction
- Signal Confirmation Time
- Signal-to-entry execution delay
- Opened By:
  - AUTO PAPER
  - MANUAL PAPER
- Option contract
- Entry time
- Entry price
- Current price or exit price
- P&L
- Result
- Current lifecycle
- Exit reason
- Holding time

## Result classification

Open positions show:

`Result = OPEN`

Completed positions are classified as:

- `PROFIT`
- `LOSS`
- `BREAKEVEN`

Lifecycle displays:

- `CLOSED_PROFIT`
- `CLOSED_LOSS`
- `CLOSED_BREAKEVEN`

depending on realized P&L.

## Position provenance

For a selected trade, the dashboard displays:

- parent Red Bar Signal ID
- Signal Type
- Direction
- selected CE/PE
- automatic/manual paper source
- P&L
- current status

The parent signal is resolved directly from `signal_attempts` using the
persisted `signal_id` already stored on the paper order.

## Trade Timeline

Selecting a trade builds a chronological timeline from:

1. Red Bar signal confirmation
2. execution state events
3. paper entry
4. paper exit when completed

Existing lifecycle events can include:

- SIGNAL_CONFIRMED
- CANDIDATE_SELECTION
- WAITING_FOR_ENTRY
- OPEN
- MONITORING
- EXIT_TRIGGERED
- CLOSED
- SKIPPED_STALE
- ERROR

The selected trade therefore acts as a lightweight flight recorder.

## Open positions

The Open Paper Position table now also shows:

- Signal Type
- Direction
- Opened By

alongside the existing:

- Signal
- Option
- Entry/current price
- P&L
- MFE
- MAE
- Stop
- Target
- Status

## Closed trade journal

The journal now includes:

- Signal Type
- Direction
- Opened By
- PROFIT / LOSS / BREAKEVEN result
- Holding time
- Exit reason

The existing paper statistics remain:

- closed count
- winners
- losers
- win rate
- realized P&L
- profit factor

## Safety

This release does not enable live execution.

Paper trades remain virtual Red Bar records.

The live execution foundation remains hard-disabled.

## Next

The lifecycle/provenance records are now suitable inputs for the future AI
Learning dataset and for a later event-driven Signal Dispatcher.
