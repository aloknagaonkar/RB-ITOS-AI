# RB-0.7.6.2 — Shadow Validation & Intelligence Analytics

RB-0.7.6.2 measures the new Shadow Intelligence layer without changing the
existing paper execution engine.

## Safety / architecture

The Current Decision Engine remains frozen.

The Shadow Intelligence and Shadow Validation layers have:

`Execution Impact = NONE`

They cannot open, block, close, reverse, hedge, or modify a paper trade.

`execution/automation.py` does not import the validation layer.

## Shadow Validation Dashboard

A new dashboard is available under:

`Intelligence -> Shadow Validation Dashboard`

It measures the relationship between completed paper trades and the Shadow
evaluation saved for the same Red Bar signal.

### Current Engine Win Rate

Calculated from CLOSED `PAPER-STD` executions:

- win = realized P&L > 0
- loss = realized P&L < 0
- breakeven = realized P&L == 0

### Shadow Accuracy

RB-0.7.6.2 intentionally uses conservative validation.

A Shadow result can be resolved when:

1. Shadow agrees with the executed CE/PE:
   - executed trade wins -> Shadow correct
   - executed trade loses -> Shadow wrong

2. Shadow says WAIT:
   - executed trade loses -> Shadow correct
   - executed trade wins -> Current Engine correct / Shadow wrong

An opposite-direction Shadow call is NOT assumed to have won merely because the
executed trade lost.

Example:

- Current Engine executed BUY PE
- Shadow said BUY CE
- PE lost

Result:

`UNRESOLVED`

The system requires a future counterfactual replay of the CE contract before it
can say whether BUY CE would actually have been better.

This prevents inflated Shadow accuracy.

## Agreement Analytics

The dashboard displays:

- agreement count
- agreement rate
- agreement win rate
- disagreement count
- Shadow Better
- Current Better
- unresolved comparisons

A trade-level table shows:

- Signal ID
- Current executed action
- Shadow action
- agreement
- actual trade result
- realized P&L
- validation classification
- Shadow confidence
- evaluation timestamp

## Intelligence Scoreboard

Every Shadow module is evaluated separately when the outcome can be resolved.

The scoreboard contains:

- module
- status
- resolved samples
- correct
- wrong
- unresolved
- accuracy
- resolved coverage
- promotion state
- execution impact

Modules continue to have execution impact NONE.

## Evidence lifecycle

New intelligence remains:

`OBSERVE`

A module becomes a validation candidate only when the current review threshold
is met:

- at least 30 resolved samples
- accuracy >= 70%
- resolved coverage >= 50%

When that threshold is met the dashboard shows:

`VALIDATED / CANDIDATE`

This does NOT automatically add the module to the Current Decision Engine.

Promotion still requires explicit review and approval.

## Recommendation Stability

The dashboard tracks the latest consecutive Shadow recommendation streak.

It shows:

- current Shadow decision
- stable duration in minutes
- consecutive evaluation samples
- streak start
- last observation
- latest Shadow confidence

This gives visibility into whether BUY CE / BUY PE / WAIT is persistent or
rapidly changing.

## Operations Center

Operations Center now includes a Shadow Validation Snapshot:

- Current Engine Win Rate
- Shadow Accuracy
- Agreement Rate
- latest stable Shadow decision
- stability duration
- resolved sample count

Detailed module analytics remain in the Intelligence page.

## What this release does NOT claim

RB-0.7.6.2 does not claim that the Shadow Engine has a virtual win rate for
opposite-direction trades.

It does not infer unseen CE/PE price paths.

It does not promote any module automatically.

It does not enable automatic reversal.

It does not enable live execution.

## Next release

Planned:

`RB-0.7.7 — Decision Audit, Why-NOT & Event Stream`

Targets:

- explicit WHY NOT decision explanations
- richer recent-event stream
- portfolio timeline
- trade health observations
- reverse would-have tracking foundations

After that, a historical counterfactual replay engine can validate opposite
Shadow decisions using actual historical option candles.
