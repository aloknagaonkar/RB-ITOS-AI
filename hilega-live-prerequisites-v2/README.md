# Combined live-prerequisite evidence refresh and trust preparation

This batch moves from synthetic qualification to actual GET-only broker evidence for **2 November 2026**, using the currently running closed worker's read context. It preserves the installed release, controller, environment and live databases.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-live-prerequisites-v2.zip
.venv/bin/python hilega-live-prerequisites-v2/manage.py \
  --repo "$PWD" \
  --active-plan "$PWD/hilega-group2-upgrade-plan-qfgbdwft/PLAN.json" \
  --active-plan-sha256 4dc497c053d41c136559b3c4ef9918598ddc6bb1b3f5447fe89032a79456c7f5 \
  --evidence-review "$PWD/hilega-group2-evidence-review-fn9zw7je" \
  --finance-review "$PWD/hilega-posttrade-finance-review-748r9kq6" \
  --session 2026-11-02 \
  --broker-read
```

The date is deliberately the previous captured session, not today's trade book. Requires current token/profile access in the worker's existing read configuration, previous signed evidence/finance files, the earlier rollout tools, dotenv and pytest in the existing venv. Installs no packages. Omit `--broker-read` for offline checks only; that cannot resolve real-evidence blockers.

## One combined batch

- Verifies the current deployed status with registration-rollout v1 before/after.
- Runs 18 pure VM validation cases: 8 existing finance and 10 historical pagination/corroboration cases.
- GETs the previous session's charges, P&L metadata/pages, historical trades and profile, with bounded pagination, fixed endpoints, request timeouts and signed private evidence. No order POST/PUT/DELETE, no retries, and no controller/service commands.
- Confirms account identity before/after and verifies signatures/scope of the earlier account and finance captures. Checks source PID stability.
- Compares fresh report counts/charges with the prior finance capture. Matches historical trade ID/exchange/side/quantity/price against earlier daily trade evidence; date/contract identity/ownership/timezone certification are explicitly separate.
- Produces a requirements packet with the actual account scope only if profile capture passed, proposed account-specific issuer/key/registry paths, mode requirements and exact active release/policy bindings. It creates **no key or registry** and will not overwrite/rotate an existing key. The packet is a proposal, not an executable provisioning approval.

## Documentation findings

See `DOCUMENTATION-REVIEW.md`. The official charges example contains `ipft: null`; that is not by itself a malformed response. Null is not converted to zero. Component arithmetic is labelled `NOT_ASSESSABLE_NULL_COMPONENTS` when necessary. The old finance validator and all its no-release flags are retained.

The reviewed trade timestamp field description does not establish its timezone. Historical rows contain a trade date, not independent timestamp semantics. This batch cannot legitimately clear that blocker simply by matching fields. `SUPPORT-DRAFT.md` contains the precise outstanding broker questions; nothing is sent.

## Outputs and boundaries

Creates `hilega-live-prerequisites-review-*` with test logs, current status, signed/private broker captures, public safe summaries, `RESULT.json`, `ISSUER-PROVISIONING-REQUIREMENTS.json` and `MILESTONES.md`. Raw account/trade/finance details remain in owner-only files. Do not paste private raw files or credentials into chat; paste the printed summary.

A historical-trade endpoint/schema failure is reported separately if the finance capture still completes; partial history is never called complete. A blocked token/network/provider capture returns a safe reason and no readiness approval. Empty or changed reports are not assumed final. No synthetic funds, fee estimates, timestamp corrections, ownership assumptions or broker cash addback are introduced.

Finality, per-trade fee attribution, strategy ownership, actual issuer provisioning, fresh real enrollment, exact activation/recovery approval and gate-release readiness remain requirements until supported. Production execution is disabled throughout. This package has no provisioning/apply/resume action.

No behavioral tests ran on the development host. Local checks: syntax/AST, preserved finance validator bytes, fixed GET allowlist and ZIP integrity. VM results are required.

## V2 observed pagination correction

The actual API response uses `metaData.page` (camelCase), with `total_records=2`, `page_size=100` and `total_pages=0`. V2 supports this spelling alongside the documented aliases and still rejects conflicting simultaneous aliases. Raw responses are never rewritten. Traversal uses the page bound derived from record count and returned page size, limited to five pages. The collected row count must equal `total_records`; otherwise capture remains incomplete. A positive declared page count conflicting with the calculated bound is rejected. The reported zero/count inconsistency remains visible in the summary; its broker semantics are not asserted as confirmed. No timezone, fee, ownership or execution clearance follows from row-count completeness.
