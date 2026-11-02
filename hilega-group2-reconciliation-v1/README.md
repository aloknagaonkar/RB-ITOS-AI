# Group 2 combined reconciliation candidates

Run `.venv/bin/python hilega-group2-reconciliation-v1/manage.py --repo "$PWD"`.

Runs 12 new pure candidate tests, then the existing pinned Group 2 tool with --broker-read (12 tests plus fresh signed GET-only account/funds capture and closed-deployment checks). Reads preparation count and owner-table names using SQLite read-only mode. Creates audit files only; no SQL writes, authority provisioning, service changes, enrollment or orders.

Reservation rules model local holds only and never add cash back to broker balances. Fee attribution requires explicit complete coverage and maps components to unique trades; net cashflow is not certified net P&L. Neither candidate is deployed. The owner-table scan and total preparation count cannot certify freshness, active state, ownership, or enrollment eligibility. A fresh disabled preparation, trusted authority and signed ownership remain prerequisites.

No behavioral tests executed locally; run on VM. Prior 314-case regression is not reexecuted. Fresh capture is authorized by the requested continuation of Group 2.
