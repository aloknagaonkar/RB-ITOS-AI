# Red Bar changes v2

Replace/add the matching files under:
`red-bar-lab-standalone-rb-2.0.0-institutional-intelligence/`

Covered changes:

1. Candidate outcome
   - No `EXPIRED` final outcome.
   - Failed or duplicate candidates become `NOT_ELIGIBLE`.
   - They are not active and cannot move to execution.

2. Mid-session candle
   - Uses the complete 12:45-13:15 30-minute candle.
   - Requires all 30 one-minute rows.
   - A delayed row is retried on subsequent scans.

3. Investigation archive and visibility
   - `NOT_ELIGIBLE` records are retained as archived investigation records.
   - They are excluded from active rank, opportunity and execution views.
   - `archive_payload()` produces the record to persist using the project's
     existing candidate lifecycle/history database insert path.
   - `active_candidate_rows()` must be applied before rendering active candidate
     or queue tables.
   - `investigation_candidate_rows()` may be used only in collapsed diagnostics
     or historical investigation pages.

Run:
`python -m pytest red_bar_lab/tests -q`
