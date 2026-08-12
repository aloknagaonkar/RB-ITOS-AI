# RB-1.5.2b — Expiry Resolution Engine

Diagnostics/stability release only. No trading-rule changes.

## Changes
- Robust provider expiry normalization (ISO date/datetime, common date displays, dict/SDK forms).
- Provider-driven replay expiry selection: first available provider expiry on or after replay trading date.
- Never back-select an expiry before the trading date.
- Replay diagnostics now show parsed expiry count, previous expiry, next eligible expiry, candidate expiries, selection rule, and selected expiry.
- Contract discovery proceeds only after a valid eligible expiry is resolved.

## Trading logic
Unchanged: Primary, Opportunity Health, Committee, Portfolio, Shadow informational-only behavior, queue, and Exit Engine.
