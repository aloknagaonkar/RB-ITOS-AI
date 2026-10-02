# Historical OI Auto Enrichment + UI V1

This package completes the proven dual-basket workflow.

## Build pipeline

Phase A:
- download/build raw moving ATM ±5 (11 strikes);
- inspect exact 09:20 ATM and full-day moving ATM path.

Coverage:
`required_raw_wings = 5 + max absolute ATM drift in strike intervals`

Phase B:
- only if required wings > 5, rebuild the raw sidecar using the wider coverage.

Analysis remains frozen:
- Moving research basket is still current ATM ±5.
- Fixed session basket is still exact 09:20 ATM ±5.
- Wider wings are raw-data coverage only.

Then:
- run Historical OI enrichment;
- require exact timestamps and exact strikes;
- write enriched JSON/CSV;
- write stable auto positioning alias;
- expose enriched sessions/rows through API.

## UI

Adds an ENRICHED source option when the current Historical OI source-selector
markup matches the expected source structure. The backend API is installed
regardless; if the button cannot be safely located, the patch prints a warning
rather than blindly editing unrelated JSX.

## Provenance

The frozen canonical 90-session dataset is never modified.

No nearest strike, nearest timestamp, interpolation, synthetic OI, or broker
execution is introduced.
