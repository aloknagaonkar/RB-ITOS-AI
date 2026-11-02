# Lifecycle companion compatibility for the approved closed hook

Confirmed startup failure: the operational lifecycle package still pins source.py to dbfce300... while the approved installed hook is d451edda.... The companion correctly refuses the changed runtime. The earlier rollout omitted this dependent integrity-pin chain.

This narrowly validates the exact approved Source change (one guard import plus the run_source_once decorator), the exact installed guard hash, all unrelated package modules/runtime hashes, the original manifest digest pin, and the companion's original CLI pin. It then derives a new manifest with only the Source pin replaced and the guard pin added, a CLI with only EXPECTED_MANIFEST changed, and a companion with only CLI_SHA changed. AST comparison rejects any other code changes.

## VM command

Services must remain stopped and the original approved rollout transaction must remain STARTUP_FAILED_SERVICES_STOPPED. The lifecycle unit may retain its failed marker. Original rollout files, plan, hook sources and code/database backups are not edited.

```bash
.venv/bin/python hilega-reference-compatibility-v1/fix_reference.py --repo "$PWD" --apply
```

This runs six synthetic safety tests and the staged companion's check_package only (no run_once/account capture). It backs up the three dependent files privately before updating them. The installed companion's check_package must then pass. Failures during the write/check block restore the three originals unless an external edit requires manual recovery. After success it clears only the stopped lifecycle unit's failed marker, without starting services.

Omit --apply for a check-only review. Neither mode starts services or reads broker credentials/account rows. The approval is limited to compatibility with the already approved closed hook; no order authority is created. Do not update hashes for unrelated changes or bypass integrity checks. No local behavioral tests were run; syntax checks only.

Expected applied status: COMPATIBILITY_APPLIED_SERVICES_STOPPED. Share the report before retrying managed startup. Existing installed hook sources remain unchanged. The original startup recovery tool can then verify current code/environment and attempt bounded startup. If it fails, preserve the transaction and diagnostics.

The private review folder retains original manifest, CLI and companion files plus a transaction/report. Power loss between writes requires review of those backups before restarting; no automatic repeated application is provided. Package integrity guards remain active and now also pin the new guard module. Production execution and readiness remain false.
