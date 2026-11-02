# After-hours historical finance review

The default command runs eight offline tests and checks deployed status before/after. --broker-read additionally uses the running source worker's existing read context and account pin for fixed GET-only historical F&O charges, report metadata and bounded realised P&L pages. No current market signal or live trading session is required by this tool. Broker report availability/finality is not guaranteed by the API documentation; empty or changing reports remain review-only.

A one-day dd-mm-yyyy range and correct April-based financial_year are derived from --session; segment is fixed FO. Maximum five pages, each at most 100 rows; response limits, eight-second GET timeouts, no retries and the existing no-redirect opener apply. Profile is checked before/after. The supplied earlier private signed account evidence is verified with the matching account pin and same IST evidence date. No timestamp normalization is performed.

Charges are aggregate date/segment records, not per-fill strategy allocations. Unknown/null components are not treated as zero. Component sums are checked to paise; the raw values are preserved. Report page-count agreement is not proof of cost basis, finality or ownership. No proportional fee splitting, cash addback or reservation release occurs. Net P&L is not certified.

All raw financial records remain in private files; public results contain counts/booleans/schema issues only. Tests do not access credentials or network. Optional historical reads save account-signed evidence. Only new review files and prior status checklist updates are written; no application database, service configuration or controller is changed.

Official contracts checked 2 November 2026:
- https://upstox.com/developer/api-documentation/get-trade-charges/
- https://upstox.com/developer/api-documentation/get-report-meta-data/
- https://upstox.com/developer/api-documentation/get-profit-and-loss-report/

Local checks: Python syntax and ZIP CRC only. Behavioral tests run on the user VM.
