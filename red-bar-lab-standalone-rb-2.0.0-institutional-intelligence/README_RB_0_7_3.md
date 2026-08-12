# RB-0.7.3 Workspace Architecture

This release reorganizes the Red Bar Lab UI so Live Trading remains focused
and research/intelligence tools can scale without crowding the live screen.

## Sidebar workspaces

- Dashboard
- Live Trading
- Research Lab
- Signal Explorer
- Level Explorer
- Trade History
- Intelligence

## Research Lab

Historical Data and Bulk Historical Backtest now live together in Research Lab.

## Intelligence

The following collectors/builders were moved out of Live Trading:
- Market Context Engine
- Volume & Structure Context
- Intelligence Foundation dataset builder

The Intelligence workspace also includes:
- Dataset Health
- reserved Options Context area for the upcoming collector

## Live Trading

Live Trading now contains only live-monitor and trade-oriented information.
No market-context, volume-context, or dataset-building controls are rendered
inside the Live Trading workspace.

## Strategy safety

This is a workspace/UI organization release. It does not change signal,
entry, exit, actionable-model, benchmark, backtest, or market-context rules.

The actual Options Context Collector (PCR/OI/Greeks/IV/option-chain capture)
will be implemented next inside the reserved Intelligence workspace.
