# Historical OI Canonical 90 Orchestrator V1

Purpose: safely extend the proven Historical OI dual-basket enrichment workflow
across the frozen canonical 90-session population.

## Important safety rule

The orchestrator never guesses an expiry.

Expiry is RESOLVED only when an existing Historical OI build or an existing
historical-positioning cache contains:
- exact matching session_date,
- explicit expiry,
- status AVAILABLE,
- actual CE and PE instrument keys,
- actual CE and PE OI.

If no verified source exists:
- EXPIRY_REQUIRED

If conflicting verified expiries exist:
- EXPIRY_AMBIGUOUS

## Two modes

Dry-run (default):
- scans all canonical dates;
- resolves expiry evidence;
- does not download anything;
- outputs READY / EXPIRY_REQUIRED / EXPIRY_AMBIGUOUS / SKIPPED_COMPLETE.

Execute:
- add `--execute`;
- only READY dates enter the existing auto-enrichment pipeline;
- auto-enrichment keeps analytical wings exactly ±5 and widens raw wings only
  as required by full-day ATM drift.

## Canonical dataset

The frozen canonical CSV is read-only and is never rewritten.

## Recommended workflow

1. Dry-run all 90 dates.
2. Inspect status counts and ambiguous expiries.
3. Execute a few READY dates as a pilot.
4. Only then execute the full READY population.
