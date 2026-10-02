# Historical OI Download / Build V1.2 — Data Quality Hardening

Problem discovered on 2026-09-09:
- sidecar envelope said AVAILABLE
- row_count was 4125
- but CE/PE instrument keys, premiums and OI were null
- all positioning states were UNAVAILABLE

Therefore row count and envelope status are insufficient.

V1.2 COMPLETE requires:
- process return code 0
- positioning CSV exists
- one available session
- session status AVAILABLE
- at least one CE/PE instrument pair
- at least one CE/PE OI pair
- at least one CE/PE premium pair

If the envelope is AVAILABLE but all three usable-data counts are zero, the job
terminates as INVALID_CONTRACT_DATA and instructs the user to verify expiry.
It does not waste retries because that condition is deterministic.

Transient partial/provider failures still use the 3-attempt retry policy.
