# Historical OI Cache Reuse + Rate Limit V1

Diagnosis from the 90-session run:

The first failing dates were not missing historical data. For example:
- fresh 2026-06-03 Phase-A build returned UNAVAILABLE because Upstox rate limiting;
- the pre-existing exact `2026-06-03 / 2026-06-09 / w5` historical-positioning cache is AVAILABLE with 4125 rows.

Therefore the acquisition path was unnecessarily refetching data already present locally.

This patch:
1. Reuses a verified exact `(session_date, expiry)` local positioning artifact for Phase A.
2. Rejects AVAILABLE shells with null CE/PE instruments or OI.
3. Computes required raw wings from the reused Phase-A artifact.
4. Reuses any existing adequate wider artifact if present.
5. Calls Upstox only when the required wider width is not already available.
6. Retries provider/rate-limit failures with 60s then 180s backoff.
7. Patches the canonical-90 orchestrator to use this safer path.

The analytical basket remains exactly ATM ±5.
The frozen canonical dataset is not modified.
