# RB-0.8.0 — Architecture & Performance Stabilization

RB-0.8.0 restructures the Streamlit UI without changing trading rules.

## UI architecture

`red_bar_lab/ui/workspace.py` is now a thin dispatcher instead of a 6,000+
line page implementation.

New structure:

red_bar_lab/ui/
- workspace.py
- _shared.py
- pages/
  - operations_center.py
  - paper_trading.py
  - research_lab.py
  - live_trading.py
  - level_explorer.py
  - signal_explorer.py
  - trade_history.py
  - intelligence.py

Each page now executes through its own `render_page(...)` function.

## Refresh architecture

The old browser JavaScript refresh was removed:

- no `setTimeout`
- no `window.parent.location.reload()`

Paper Trading now uses a dedicated 5-second Streamlit fragment for:

- background monitor heartbeat
- current monitor state
- open-position count
- aggregate open P&L
- last monitor decision

This fragment reads live SQLite state directly and does not rerun the entire
Paper Trading page.

Candidate ranking is deliberately NOT recomputed every 5 seconds. Use the
existing `Refresh & Rank Candidates` control when a new ranking snapshot is
needed.

## Correctness-first caching policy

The following live reads remain uncached:

- open paper positions
- unrealized P&L
- paper monitor heartbeat
- execution marks / state

These values are updated by the standalone paper monitor and must not be hidden
behind a stale UI cache.

Existing safe caches for market-intelligence/service objects remain intact.

## Performance Diagnostics

Paper Trading now includes a collapsed `Performance Diagnostics` panel.

It measures:

- Market intelligence
- Portfolio / history
- Signal context
- Market / account / Red Bar
- Candidate ranking + analysis
- Execution / lifecycle
- Open position + exit engine
- Diagnostics / journal / final render
- TOTAL PAGE RENDER

It also identifies the slowest section.

This allows performance work to be driven by measurements rather than guesses.

## Trading logic unchanged

RB-0.8.0 does not change:

- Red Bar detection
- CE/PE direction mapping
- candidate ranking rules
- Rank #1 execution authority
- Shadow Intelligence authority
- paper-entry gates
- hard premium stop
- +15% breakeven
- +20% trailing activation
- 10% trail distance
- Target 1
- 15:25 EOD exit
- NIFTY thesis invalidation
- opposite Red Bar exit
- option technical breakdown
- Exit Engine Idle Preview

Live broker execution remains hard-disabled.

## Validation

The complete regression suite is run after the refactor. UI compatibility tests
now scan the modular UI package instead of assuming all source lives in
`workspace.py`.
