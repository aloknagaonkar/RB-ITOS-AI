# Historical OI Enriched Source Button V1

The automatic enrichment backend and API were already working, but the generic
UI patch could not recognize the exact source-button markup and therefore did
not insert the ENRICHED selector.

This narrow patch:
- changes only `frontend/src/historicalOiResearch.tsx`;
- finds the existing BUILT source button by behavior (`setSource('BUILT')`);
- inserts an `Enriched` source button beside it;
- verifies the Source union and enriched API endpoint wiring before writing.

No OI/PCR calculations, enrichment data, strategy rules, or backend behavior
are changed.
