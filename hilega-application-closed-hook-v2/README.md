# Application closed-hook staging — v2

Run on the VM from ~/RB-ITOS-AI:

```bash
unzip hilega-application-closed-hook-v2.zip
.venv/bin/python hilega-application-closed-hook-v2/apply_and_check.py --repo "$PWD"
```

Default: 12 targeted VM cases, with semantic source parity against 41 prior files. Optional release check: append --full for the expected 179 cases. No behavioral tests were run in the artifact-building workspace. The previous 163 full cases and 13 targeted cases are prior VM evidence, not new results.

This package copies isolated candidate/check files to HOME, refusing differing existing targets. It verifies the exact installed worker SHA reported by your VM, stages a preparation-only call-site wrapper and closed boundary, and queries related service metadata read-only. It does not replace installed scripts, execute the application main, open application databases, read environment files, install units, restart services, or enable order execution. Raw service arguments are not written to reports. A missing service mapping is reported for follow-up, not treated as deployment proof.

The stage is a review candidate, not a deployment bundle. Its dependency/release manifests and actual preparation-to-execution data contracts require review before installation. The application call-site tests use a mock bridge; the existing real fixture consumer test separately verifies synthetic execution. This does not prove the actual running application delivers executable events.

Results: QUICK-VALIDATION.json (or FULL-VALIDATION.json) here; DISCOVERY.json in the reported staging folder. Send those JSON reports back for the next step. No secrets or .env files are needed.
