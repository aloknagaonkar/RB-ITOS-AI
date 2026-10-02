# Historical OI Download / Build V1.1 — Retry Hardening

Adds automatic cache-aware retries to the new-date Historical OI build flow.

Policy:
- maximum attempts: 3
- after attempt 1 failure/PARTIAL: wait 15 seconds
- after attempt 2 failure/PARTIAL: wait 60 seconds
- attempt 3 is final
- COMPLETE only when the sidecar reports AVAILABLE and positioning CSV exists
- PARTIAL after all attempts if provider status remains PARTIAL
- FAILED after all attempts for non-PARTIAL failure

The job does not pass `--refresh`, so the existing positioning sidecar can reuse
successful cached session data on retries.

UI states:
QUEUED → RUNNING → RETRYING → RUNNING → COMPLETE/PARTIAL/FAILED

The status file records attempt history, provider status, row count and next retry delay.
