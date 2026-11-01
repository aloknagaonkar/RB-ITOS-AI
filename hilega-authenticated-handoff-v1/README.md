# Historical authenticated handoff — v1

Current step: verify an existing application preparation's historical provenance without adopting it for execution.

Run on VM from ~/RB-ITOS-AI:

```bash
unzip hilega-authenticated-handoff-v1.zip
.venv/bin/python hilega-authenticated-handoff-v1/apply_and_test.py --repo "$PWD"
```

Expected 12 targeted cases: actual Source plus atomic disabled binding, repeat read without extra preparation/capture/attempt, seven local-record tamper cases, consumption mismatch, changed request state, journal chain tampering. All databases/evidence in tests are temporary and synthetic. No behavioral pytest was run while building this ZIP; syntax and ZIP integrity only. The runner pins seven application/test source files to the reviewed GitHub checkpoint and stops on differences. It installs no HOME modules and changes no services.

Why required: application Source has already reserved a local reference and created a disabled request. Calling the fixture preparation path again would create separate admission state, not safely adopt that record. This verifier follows signed reservation fingerprints through plan/hold/outbox, binding, signed evidence, disabled request, consumed event, cursor and journal chain. It refuses altered or already-attempted request records instead of creating replacements.

Security/accuracy boundaries: account evidence and local reservation have signatures; the application binding is cross-checked through the signed reservation, not independently signed. The journal is hash-chain verified, not externally authenticated. A self-consistent rewritten journal is not a trusted external signature. Evidence validation uses the historical plan creation time, not present-day freshness. No current cash, price, controller or production authorization clearance is granted. Other unresolved account/request activity still requires separate review. No real database or broker endpoint is inspected by this test runner.

This is a read-only historical verifier, not an execution adoption adapter. Do not install it into the running hook or use its return value as a grant. Caller owns the lock and attached read transaction; this cannot provide remote broker atomicity. Production execution and reservation release remain disabled.

## Milestone checklist

| Milestone | Evidence / status |
|---|---|
| Reusable cycles, journal/reversal/partial exit recovery | Prior 163-case full VM pass |
| Closed worker and bounded restart | Prior 13-case targeted VM pass |
| Application hook staged | Prior 12-case targeted VM pass |
| Supervisor-to-worker mapping | Confirmed from VM diagnostics |
| Actual Source structural handoff observation | Prior 10-case targeted VM pass |
| Historical signed binding verification | Current 12-case VM gate; pending |
| Current evidence/control revalidation and durable adoption contract | Pending |
| Actual application exit integration and recovery | Pending |
| Full dependency/release manifest reconciliation | Pending |
| Combined regression and managed closed deployment/rollback | Pending |
| Trusted production authority, policy approval, fresh broker validation and pilot | Pending |

Prior passes are previous VM reports, not repeated by this package. A targeted pass does not establish full regression or production readiness. No new percentage or completion-time estimate is implied.

Return VM-VALIDATION.json to continue. The next implementation must bind an approved adoption decision atomically to the existing request without creating another plan/hold/request, while keeping recovery and execution authorization separate.
