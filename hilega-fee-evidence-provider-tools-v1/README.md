# Read-only aggregate fee evidence provider v1

This adds a real fixed GET-only report collector, not an execution or risk gate.
It is not installed into the running application.

## VM validation and capture
    .venv/bin/python -m zipfile -e hilega-fee-evidence-provider-v1.zip hilega-fee-evidence-provider-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-fee-evidence-provider-tools-v1 -p 'test_*.py' -v
    PYTHONPATH=backend:. .venv/bin/python hilega-fee-evidence-provider-tools-v1/fee_report.py check --capture-report

26 independent offline tests must pass before the explicit capture command.
The tests mock every network call; the capture command performs actual broker
GET reads on the VM. No service restart or activation is involved.

The CLI checks pinned installed source files and local PAUSED/PREPARATION_ONLY
state, reads the existing private account pin, and obtains the token from the
existing shell/.env configuration without printing it. Conflicting values for
the same token setting block. It verifies the pinned profile before and after
one fixed trade-charges GET, for the current IST date and FO segment. Financial
year is calculated across the April boundary. Profile checks use the existing
installed fixed GET account client and identity matcher.

There are no retries, redirects, arbitrary URLs or broker mutation methods.
Responses and the overall collection time are bounded. Provider errors do not
fall back to old reports or fabricated zeros.

## Evidence and output
Successful collection writes a locally HMAC-signed envelope to a new private
directory under data/research/hilega-fee-report-*/fee-report-private.json.
The directory is private and its files are owner-only. The capture includes the
exact requested dates/segment/year, actual local collection timestamps, provider
response normalized to decimal strings, and the classification of the aggregate
fee total. This is locally pinned integrity, not a broker-issued signature.
The CLI prints only the summary and the private directory path.
Do not upload or commit the private evidence folder, .env or account pin.

Expected success status: CAPTURED_AGGREGATE_REPORT_RISK_STILL_BLOCKED.
Provider errors may instead return STOPPED_FOR_REVIEW. Do not bypass the checks.

The trade-charges endpoint documents a date/segment aggregate. It does not
provide per-order fee attribution in that response. Capturing it now does not
establish the underlying report's same-day completeness, finality, or freshness.
Report capture timestamps must not be substituted for a provider data-as-of time.
No strategy fee allocation is invented from aggregate totals.

Null or missing charge components remain unknown, not zero. Total and known
components use exact integer paise; invalid, negative, nonfinite or fractional
paise values require review. A known-component sum exceeding the aggregate total
blocks. A smaller sum remains an explicitly unexplained difference. Even matching
arithmetic and explicit zero components cannot grant fee completeness.

fees_complete, strategy ownership, report completeness/finality and risk-ready
flags remain false. Realized/open net P&L remain null. The report cannot authorize
entry, release, or live trading.

## Official documentation checked 2026-10-29
- Trade charges: https://upstox.com/developer/api-documentation/get-trade-charges/
  Date/segment/year report, charges_breakdown total and fee components.
- Brokerage calculator: https://upstox.com/developer/api-documentation/get-brokerage/
  Order-parameter charge calculation; not substituted for final incurred fees.
- Realised report: https://upstox.com/developer/api-documentation/get-profit-and-loss-report/
  Separate paginated report; this collector does not query or adopt it as net P&L.

## Validation and remaining work
26 local tests passed with ResourceWarning treated as an error. VM/live provider
validation is pending; no live API call was made locally.
No application database, trading control, source worker, credential, configuration
or risk limit is modified. Only a new private evidence directory is written by
the explicit successful capture.

Per-fill fee attribution, authenticated strategy ownership and net P&L, production
daily-stop, real reservation, live lifecycle integration and pilot validation
remain pending. No production limit has been selected or enabled.
