# Second application-cycle candidate v2: final-commit evidence fix

The v1 VM run reported 127 passed, 6 failed and 8 errors. I left a first-entry
fresh_plan() call at the final pre-commit step when adapting the candidate.
That check rejects historical order activity even after it has been attributed.

This v2 uses the full history-aware current-state check at that final point.
It does NOT remove the installed evidence gate or ignore generic historical
activity without proof. Before attempt insertion, no current attempt is allowed.
At the last in-transaction check, exactly the attempt this transaction just
inserted is allowed, with matching ID/request/operation/wire and IN_FLIGHT state.
Any other attempt goes to recovery. The final check revalidates history, original
signed account/cash captures, market/quote freshness, controller, signal, lease,
contract and budget. It remains inside the claim/adoption/attempt transaction.

Two added regression cases cover expiry after attempt insertion and a quote that
becomes stale only at the final commit check. They must roll back the candidate
claim/adoption/attempt while preserving the closed first cycle.

## Run on VM

Keep v1 and its failed report. Extract this ZIP into its separate v2 directory:
unzip hilega-second-application-cycle-v2.zip
.venv/bin/python hilega-second-application-cycle-v2/apply_and_test.py --repo "$PWD"

Expected 143 combined integration cases (prior 122 plus 21 second-cycle cases).
--new-only selects 21. The prior 122-case next-preparation folder and the expanded
104-case cycle-close folder remain required. No v1 source is overwritten.
Package hashes, prior candidate hashes, installed source pins and Python syntax
are checked on the VM before behavioral tests. This is not a full release suite.

This fix was assembled while the execution workspace was unavailable. ZIP
structure, CRC and payload hashes were checked in memory. Python syntax and
behavioral pytest are pending VM validation; no passing result is claimed.

Production execution, services, the application branch and existing VM runtime
are unchanged. Positive order tests remain intercepted with synthetic records.
The previous 122-case pass remains the last completed integration checkpoint.
The second complete cycle milestone is still pending until v2 passes.

## Original scope retained in v2

This isolated package connects the history-aware disabled preparation from the
122-case milestone to its BUY claim/attempt, signed fill/position review, actual
Source closed EXIT, candidate SELL, flat closeout and local reference retirement.
A final test reviews a third fresh signal against both complete cycle archives.
No service hook, production order authority or broker network is enabled.

## Run on your VM

Download hilega-second-application-cycle-v2.zip from the isolated candidate branch,
place it in ~/RB-ITOS-AI and run:

```bash
cd ~/RB-ITOS-AI
unzip hilega-second-application-cycle-v2.zip
.venv/bin/python hilega-second-application-cycle-v2/apply_and_test.py --repo "$PWD"
```

Expected combined 143 cases: prior 122 plus 21 new second-cycle cases. Optional
--new-only selects 21 new cases. This is an integration checkpoint, not the full
repository release regression. The expanded previous hilega-history-aware-
preparation-v1 and hilega-application-cycle-close-v1 folders and the 122-case PASS
report must remain on the VM. The runner verifies their package manifests, the
15 reviewed installed source pins, and this package's hashes. It compiles Python
before tests and checks unchanged sources afterward. No HOME modules are installed
and no existing source, controller, service or live database is changed.

For v1 artifact creation checked Python syntax; v2 Python syntax is pending VM validation. ZIP integrity was checked for both.
No behavioral pytest execution was performed here: those checks run on your VM.

## Why cycle scoping is required

The first-cycle lifecycle code assumes one BUY and one SELL are the whole account
history. The next cycle adds its own requests while old broker evidence must stay
visible and immutable. BrokerScope therefore filters only SELECT reads to one
cycle using reservation_reference and its attempt/receipt links. All writes still
reach the real attached transaction tables; no SQL write is hidden or redirected.
The history counterpart must match every archived request/attempt/receipt/claim
exactly. Unrelated or changed records are rejected, not silently ignored.

The ORIGINAL full signed account capture is verified before any reconciliation
view is formed. It is never edited, re-signed or relabelled. Every old order/trade
is matched against its cycle archive; the current cycle's orders/trades determine
its remaining quantity. Because archived cycles are flat, the signed total account
position must equal that current remaining quantity, with explicit position rows.
This is especially important when both cycles use the same option instrument.

The next prepared request's signed admission, local reservation fingerprints,
history hashes, journal event and disabled wire are verified again. Fresh signed
account/cash/market evidence, current controller review state/version, signal age,
bridge lease, one-lot quote/grid and half-cash cap checks run inside the attempt
transaction. Candidate authorization uses a key distinct from the account evidence
key. The real gate still runs before capture or claim. All positive order tests
patch both gate and transport within tests and use synthetic records/credentials.

## Recovery and financial boundaries

BUY recovery is selective: it binds only that request's durable receipt or keeps
it UNKNOWN. It never calls whole-store recovery that might rewrite a completed
cycle. SELL recovery is likewise selective and never resends. Old cycle rows are
checked byte-for-byte throughout the tests. Two pre-commit BUY failure points,
three post-commit BUY interruption points, concurrent BUY, UNKNOWN response,
actual gate refusal, signed-history tampering and selective SELL restart are
covered along with the complete second cycle.

The closeout preserves the FULL signed capture but archives broker records for
that cycle only. Gross P&L is calculated only from the cycle's own order IDs. The
full test expects two separate -325-paise synthetic gross records, not double
counting the first trade in the second record. Fees remain incomplete and net P&L
is null. Local reference retirement is not broker cash release. No automatic
residual SELL, cancel/reprice, partial-entry sizing or opposite BUY is introduced.

## Current milestone / pending

- Prior 122-case next disabled preparation checkpoint: passed on your VM.
- History-aware next BUY adoption, second complete cycle and third-signal history
  review: CURRENT package, 19 new / 141 combined VM cases pending.
- Tested scope is two complete application candidate cycles; unrestricted repeat
  cycles and actual broker behavior are not established by this package.
- Running Source/worker automatic integration, approved pricing/partial policies,
  trusted production authority, fresh real broker evidence, complete dependency/
  release reconciliation, full regression, managed closed deployment/rollback and
  explicitly authorized funded pilot remain pending.

All PAUSED/ARMED transitions and captures in the tests are synthetic temporary
fixture operations. They do not authorize trading while the real controller is
paused. Journal hash chains do not prove external authorship. Local attached
transactions are not atomic with the remote broker. The candidate APIs retain
production_execution_enabled=false and production_ready=false.

Return VM-VALIDATION.json. Do not sum overlapping suites as unique test totals.
