# RB-0.7.4 Feature Store + Options Data Infrastructure

This release completes the Layer-2 data architecture needed before options
intelligence and AI interpretation.

## Feature Store

`RedBarFeatureStore` is now the single read interface used by the Intelligence
Dataset for entry-time context.

It combines:
- RB-0.7.1 Market Context
- RB-0.7.2 Volume & Structure Context
- RB-0.7.4 Options Context

The Intelligence Dataset no longer needs to know which database table owns
each context feature.

## Options Context Infrastructure

A new SQLite table is added:

`option_context_snapshots`

Stored summary fields include:
- expiry
- option-chain snapshot timestamp
- snapshot delay from signal entry
- entry-alignment flag
- spot and ATM strike
- total Call OI / Put OI
- OI PCR
- change in Call OI / Put OI
- OI-change ratio
- Call Wall / Put Wall
- Max Pain
- ATM Call/Put IV
- ATM Call/Put Delta
- ATM Call/Put Gamma
- ATM Call/Put Theta
- ATM Call/Put Vega
- raw option-chain CSV artifact path

## Entry-alignment guard

Options data can become an AI prediction feature only when its snapshot is
captured after the signal entry and inside the configured alignment window
(default 120 seconds).

Late snapshots remain stored for research, but the Feature Store returns their
options features as null so they cannot leak future information into training.

An already entry-aligned snapshot is protected from being overwritten by a
later non-aligned manual capture.

## Intelligence workspace

Live Trading automatically captures an option-chain snapshot only when a newly confirmed signal is still inside the 120-second entry-alignment window. If there is no eligible new signal, no option-chain request is made. Options collection errors are isolated from the live trading monitor.

Options Context now supports:
- live Upstox option-chain capture for today's confirmed signals
- optional expiry selection (nearest active expiry by default)
- configurable entry-alignment tolerance
- CSV import for externally captured/historical options context
- stored-options inspection
- Feature Store dataset-health metrics

## Raw chain artifacts

Raw option-chain snapshots are written under:

`artifacts/red_bar/options/<instrument>/<date>/`

## Trading safety

No Red Bar entry, exit, signal, actionable-model, benchmark, backtest, or
trade-quality rule is changed in RB-0.7.4.

Next:
RB-0.7.5 — Options Intelligence / interpretation layer.
