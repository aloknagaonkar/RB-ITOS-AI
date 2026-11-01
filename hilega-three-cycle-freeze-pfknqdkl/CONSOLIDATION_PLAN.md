# Reusable fixture-cycle handling: next implementation milestone

## Why change the architecture now?

The first three cycles demonstrate the lifecycle and failure boundaries. Further
numbered preparation/execution/exit modules would duplicate logic and create
drift. The next implementation should use one cycle identity and one immutable
history chain, retaining the proven risk and recovery checks.

## Target flow

fresh confirmed signal -> current account/cash/market review -> disabled
preparation -> single-use fixture authorization and durable attempt -> fill
review -> linked strategy EXIT -> owned-quantity SELL -> terminal flat proof ->
signed closeout -> local reference retirement -> next fresh signal.

## Concrete scope

1. One versioned cycle record keyed by account scope, session and confirmed
   entry identity; include predecessor seal and exact request/event bindings.
2. One history-chain verifier. Store each cycle's distinct request/order/trade
   contributions once and authenticate predecessor seals. Never insert a whole
   cumulative broker snapshot as another disjoint V1 archive. Preserve original
   signed captures and prior checkpoint records.
3. One preparation/BUY/EXIT/SELL/closeout/retirement API driven by cycle identity,
   replacing the need for SECOND/THIRD/FOURTH-specific implementation modules.
4. Explicit import/compatibility validation for existing first/second/third
   fixture records; no implicit adoption of unrelated orders or old signals.
5. Fixture-only policy initially: one full lot, positive fee buffer, premium plus
   buffer <= half current verified available cash, fresh evidence, controller
   and stop/lease checks, pinned adapter, atomic local claim/attempt boundary.
6. UNKNOWN outcomes block new risk and never resubmit. Historical replay returns
   historical recovery only; it cannot claim fresh entry permission. Retain holds
   unless the exact closure and retirement checks pass.

## Acceptance evidence

- Existing 120-case regression remains passing.
- The same consolidated API completes fourth and later cycles in temporary
  fixtures, without adding another numbered implementation path.
- Demonstrate a bounded multi-cycle sequence (for example 4 and 10 cycles),
  unique claims/attempts, exact position quantities and intact prior history.
- Exercise restart, cursor replay, duplicate/concurrent events, stale cash/quote,
  changed predecessor/history, tampering, stop/pause and transaction interruption.
- Never infer indefinite live reliability from a finite fixture sequence.

## Still outside this milestone

Production authority provisioning, production pricing and partial-fill policy
approval, actual owned-contract network validation, execution-runtime deployment,
operational monitoring drills and an explicitly authorized funded live pilot.
Fees/net P&L completeness and broker cash release remain separate evidence tasks.
