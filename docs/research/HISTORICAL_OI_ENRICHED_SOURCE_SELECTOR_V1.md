# Historical OI Enriched Source Selector V1

Fixes the exact current frontend structure discovered in `historicalOiResearch.tsx`.

Changes:
- adds `ENRICHED` to the existing `<select>`;
- routes ENRICHED detail requests to `/historical-oi/enriched/rows`;
- uses the endpoint's required `date=` query parameter;
- labels the summary card as Enriched;
- adds an enrichment provenance note.

No backend calculation logic, OI/PCR methodology, canonical data, or strategy behavior changes.
