# RB-0.9.3 — Decision / Queue / Lifecycle Architecture

RB-0.9.3 separates candidate decision-making from paper execution.

## What changed

- Institutional Execution Committee can evaluate the newest confirmed signal in the Streamlit foreground.
- Foreground evaluation runs with `queue_only=True`; it never opens a paper position.
- Committee results are persisted immediately in `institutional_execution_evaluations` and `execution_queue`.
- New `execution_queue` statuses: APPROVED, WAITING, REJECTED, EXECUTING, ACTIVE, CLOSED.
- Background `run_cycle()` now performs three explicit phases:
  1. decision/queue population,
  2. approved-queue consumption,
  3. open-position monitoring/exits.
- The queue consumer does not re-score approved candidates before execution.
- Existing `execution_state_events` is retained as the single Trade Lifecycle / Decision Replay event store.
- Paper Trading UI now shows the Execution Queue and Trade Lifecycle / Decision Replay timeline.
- The old UI message saying committee results wait for the background monitor has been removed.
- Candidate rank remains discovery order only; there is no fixed trade-count limit.

## Safety preserved

Existing duplicate protection, candidate/performance gates, opportunity extension, committee probability/EV gates, paper capital checks, stop/target protection, trailing/breakeven logic, thesis invalidation and EOD exits remain in place.

## Validation

`203 passed`

New RB-0.9.3 tests validate:

- foreground committee evaluation queues but does not open positions;
- approved queue items are opened only by the queue consumer;
- queue consumption is idempotent.
