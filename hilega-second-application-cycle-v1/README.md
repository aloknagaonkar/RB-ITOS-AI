# Second complete application cycle candidate v1

This isolated package connects the history-aware disabled preparation from the
122-case milestone to its BUY claim/attempt, signed fill/position review, actual
Source closed EXIT, candidate SELL, flat closeout and local reference retirement.
A final test reviews a third fresh signal against both complete cycle archives.
No service hook, production order authority or broker network is enabled.

## Run on your VM

Download hilega-second-application-cycle-v1.zip from the isolated candidate branch,
place it in ~/RB-ITOS-AI and run:

```bash
cd ~/RB-ITOS-AI
unzip hilega-second-application-cycle-v1.zip
.venv/bin/python hilega-second-application-cycle-v1/apply_and_test.py --repo "$PWD"
```

Expected combined 141 cases: prior 122 plus 19 new second-cycle cases. Optional
--new-only selects 19 new cases. This is an integration checkpoint, not the full
repository release regression. The expanded previous hilega-history-aware-
preparation-v1 and hilega-application-cycle-close-v1 folders and the 122-case PASS
report must remain on the VM. The runner verifies their package manifests, the
15 reviewed installed source pins, and this package's hashes. It compiles Python
before tests and checks unchanged sources afterward. No HOME modules are installed
and no existing source, controller, service or live database is changed.

Artifact creation checked Python syntax, declared case counts and ZIP integrity.
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
