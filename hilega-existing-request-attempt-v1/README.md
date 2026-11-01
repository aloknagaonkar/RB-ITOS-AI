# Existing-request execution-adoption candidate — v1

## Why this matters in the flow

Confirmed signal -> application disabled preparation -> signed historical verification -> durable closed handoff -> CURRENT STEP: candidate adoption + claim + attempt -> future production execution integration -> actual fills / SELL / flat.

The application has already created its request and hold. This candidate reuses those exact references and atomically commits an adoption record in the application database plus an independently signed candidate claim and a PLACE attempt in the attached adapter database. No second prepare() call is made. This connects the previously verified application preparation to the adapter's attempt/receipt lifecycle in intercepted synthetic tests.

A claim without an attempt would spend authority without durable submission state. An attempt without a claim would bypass authorization. The attached rollback-journal transaction commits or rolls back both, with the application adoption record. After that commit, a timeout or restart can reconcile durable receipts or remain UNKNOWN; it never blindly sends the BUY again.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-existing-request-attempt-v1.zip
.venv/bin/python hilega-existing-request-attempt-v1/apply_and_test.py --repo "$PWD"
```

Default expected 20 targeted cases: 17 new attempt/adoption cases plus three prior durable-handoff regression cases. For all 49 historical/handoff/attempt cases append --integration. Neither option reruns the prior 163-case fixture lifecycle suite; this is not a full release regression.

The runner requires the previous durable closed-handoff 20-case PASS report. It pins 12 reviewed application/test sources from GitHub commit c96fbb4a55951432ddd48dcca3825350dfe1721b and verifies payload integrity. If a pin differs, stop and return the filename. No installed sources, HOME modules, service units, environment files or live databases are changed. Synthetic temporary databases and mocked transport are used for all positive order branches. No local behavioral pytest was run while building this ZIP; syntax, expected case enumeration and ZIP integrity were checked only.

## Gate and authorization boundaries

The exact installed LIVE_CLOSED Adapter/HttpTransport and source hash are required. The actual hard gate runs before new capture or claim. There is no CLI or environment setting that opens it. Positive tests patch transport.check and transport.send only inside the test, with credentials mocked to fail if accessed. No real order is submitted. HttpTransport.send itself retains its original second gate check.

The independent candidate authority key is distinct from the account evidence signing key. It is a caller-provided synthetic authority for this candidate; trusted production provisioning is NOT implemented. A ten-second candidate grant and freshly validated context are committed with the single-use claim. Account evidence, fresh cash/ask, held budget, controller version, preparation-caused PAUSED reason, stop state, bridge lease and historical request links are checked. An old durable review receipt alone grants no execution permission. Production pricing/fee policies and ARMED dispatch authorization remain unapproved/unimplemented. The tests use the existing preparation-review PAUSED state to exercise this candidate branch; this is not authorization to trade while paused.

Recovery checks the immutable request fingerprint, wire, attempt and matching signed application adoption / adapter claim before calling the adapter's durable recovery method. It does not collect, create another attempt or send. No receipt means UNKNOWN. A receipt-backed acknowledgement remains NOT_FILLED and recovery requires reconciliation. This package does not prove actual broker fills, SELL lifecycle, service wiring, or real account behavior.

The new module constructs the adapter attempt and uses the pinned adapter's existing receipt methods; it does not install or modify the staged authorizer-hook adapter. Internal adapter method changes require review and new pins.

The application and adapter are attached with DELETE journals and FULL synchronous mode; the same-filesystem requirement is enforced for this new multi-database write. Local transactions do not provide atomicity with the broker or external journal writer. Fresh journal provenance is rechecked before attempt insertion. Remote outcomes still require read-only reconciliation. Admission signatures are candidate data, not live clearance.

Output: VM-VALIDATION.json. Return its JSON to update the milestone.
