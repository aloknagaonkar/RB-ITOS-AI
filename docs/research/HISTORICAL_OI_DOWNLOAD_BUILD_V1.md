# Historical OI Download / Build V1

Adds a background UI operation for building historical per-strike positioning data for a new date.

The user supplies:
- session date
- exact expiry

The expiry is never inferred or guessed.

The job reuses the existing `market_lab.historical_positioning_sidecar` and writes isolated artifacts under:
`data/historical-evidence/historical-oi-build/<YYYY-MM-DD>/`

This V1 deliberately does not modify the frozen 90-session canonical OI library.
It also does not create production Observation snapshots, so strict Historical Replay readiness is unchanged.
