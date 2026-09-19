# Historical OI Enrichment V1.1

Fixes V1 for dates outside the frozen canonical 90-session range, such as
2026-09-09. If canonical rows are absent, exact 5-minute checkpoint rows are
generated from the downloaded positioning sidecar.

No nearest timestamp, nearest strike, interpolation, or synthetic OI is used.
