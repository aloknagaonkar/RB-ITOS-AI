# RB-1.5.2a — Diagnostics & Stability

RB-1.5.2a is an observability-only release built on RB-1.5.2. It does not change Primary scoring, Opportunity Health, Shadow authority, Committee policy, Portfolio Risk Manager policy, queue behavior, entry logic or exit rules.

## Added

- Replay Diagnostics & Health panel in Research Lab.
- Read-only underlying-data availability probe.
- Expired-expiry discovery diagnostics.
- Historical expiry-resolution diagnostics.
- Option-contract discovery diagnostics.
- Stored option-manifest diagnostics.
- Same-day ONLINE snapshot diagnostics.
- Replay-readiness/fidelity diagnostics.
- SQLite reachability, lock/journal-mode and file-size diagnostics.
- Per-stage elapsed-time visibility.
- First actionable replay failure surfaced in the UI.

## Expected 0/0 diagnosis

A `Contracts 0/0` state is no longer ambiguous. Run **Replay Diagnostics** and inspect these stages in order:

1. Underlying Data
2. Stored Option Manifest
3. Live Market Capture
4. Expired Expiry Discovery
5. Expiry Resolution
6. Option Contract Discovery
7. Replay Readiness
8. Database

The first FAIL/BLOCKED/LOCKED stage identifies where the replay path stopped.

## Trading behavior

No change.
