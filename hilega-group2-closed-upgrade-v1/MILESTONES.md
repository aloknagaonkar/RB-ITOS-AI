# Hilega milestone checklist

Evidence baseline: latest supplied VM results, 2 November 2026. Checked candidate work is not a claim of production readiness.

## Closed foundation
- [x] Closed worker deployed and old-worker rollback / identical restoration verified.
- [x] Installed pause recovery running.
- [x] VM UTC timezone and clock synchronization verified.
- [ ] Actual VM reboot recovery tested.

## Group 2 candidate and closed deployment
- [x] Combined 74 candidate tests plus one seed preflight passed previously.
- [x] All 86 candidate files and context/authority review hashes verified.
- [x] Native candidate pause recovery passed with two disposable databases.
- [x] Transactional file replacement and rollback implementation prepared.
- [ ] Current package transaction tests on VM.
- [ ] New candidate managed startup/restart on disposable state.
- [ ] Exact closed upgrade plan generated.
- [ ] Quiescent code/config/database backups.
- [ ] Candidate and matching recovery deployed; stable paused runtime verified.
- [ ] Actual new-release rollback under live service management verified.

## Broker evidence
- [x] GET account capture and cross-endpoint timestamp audit completed.
- [ ] Broker timestamp contract confirmed and any required parser correction validated.
- [ ] Fresh broker evidence and existing account activity/strategy ownership reviewed.

## Authority and enrollment
- [x] Synthetic private-context/provisioning and commit recovery tested.
- [x] Synthetic fresh-signal binding / signed reservation / replay tested.
- [ ] Independent production authority and order-policy approval.
- [ ] Approved authority provisioned and exact private context configured.
- [ ] Bounded real-evidence fresh preparation and signed owner enrollment verified.

## Finance and final readiness
- [x] Candidate fee attribution and reservation release rules tested.
- [ ] Actual fees, cost basis and P&L reconciled.
- [ ] Cash reservation release deployed and validated.
- [ ] Final integrated release regression and market/warmup readiness verified.
- [ ] Final stop, restart, uncertain-order, monitoring and recovery checks.
- [ ] Explicit final activation approval and supervised first execution.

Production execution remains disabled. Synthetic results do not certify a real order path.
