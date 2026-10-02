# Historical OI Enrichment Batch V1

The Enriched UI intentionally lists only dates that have an actual
`historical-oi-enrichment/<date>/enriched.json`.

This batch tool discovers already-built Historical OI sessions, reads the exact
expiry from each build artifact, and runs the existing auto dual-basket
enrichment pipeline for them.

It does not guess expiry dates. It does not modify the frozen canonical dataset.
It skips already-complete 74/74 enriched dates by default.

After the batch finishes, the existing Enriched sessions API will automatically
list every successfully enriched date.
