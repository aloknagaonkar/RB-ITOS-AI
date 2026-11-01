# Read-only application handoff contract — v1

Current step: inspect the committed application record contract before execution integration.

Why required: Source creates its own disabled plans/holds/outbox and pauses. The fixture consumer creates separate admissions and explicitly requires OFFLINE_FIXTURE. Blindly connecting them risks duplicate preparation or wrongly adopting an exit record that is deliberately REFUSED_CLOSED. This observer projects references only; it does not bridge authorization, import fixture admissions, consume events, or enable execution.

Run from ~/RB-ITOS-AI:

```bash
unzip hilega-handoff-contract-v1.zip
.venv/bin/python hilega-handoff-contract-v1/apply_and_test.py --repo "$PWD"
```

Expected: 10 targeted VM cases. Three exercise the actual application Source with synthetic inputs and temporary databases; five inject inconsistent records; two cover snapshot requirements and closed exit observation. The exit test uses a synthetic closed record, not a full actual exit-dispatch integration. No local behavioral tests were run when building this ZIP. Syntax and ZIP integrity were checked only.

The runner checks exact SHA256 pins for four reviewed application files from GitHub commit c96fbb4a55951432ddd48dcca3825350dfe1721b. If the VM differs, it stops rather than changing source. It runs folder-local tests; it never installs anything in HOME, reads real account evidence, accesses live application databases, changes services or calls order transport. Imported application dependencies may perform their existing dependency-pin checks during synthetic tests.

Observer limitations: it validates structural coherence in a caller-owned transaction. It does not authenticate the journal, validate binding/admission signatures, verify current freshness or authorize any use of the records. Its observation fingerprint is not a signature. It intentionally returns no executable draft. Closed exits are counted only and never adopted.

Completed prior evidence: 163 full fixture tests; 13 closed-worker targeted tests; 12 application-hook targeted tests; actual supervisor-to-worker mapping confirmed. These are previous VM results, not reruns by this package.

Pending: this 10-case gate; binding/signature and journal verification for a production contract adapter; existing-record adoption without repeated preparation; application EXIT lifecycle integration; full dependency/release-manifest reconciliation; full regression; managed closed deployment/rollback; trusted authority, policies, fresh broker evidence and authorized pilot. Production execution remains disabled. This package does not claim production readiness or complete execution integration.

Return VM-VALIDATION.json output after running.
