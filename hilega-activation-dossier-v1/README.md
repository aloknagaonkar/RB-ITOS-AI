# Combined activation, recovery and fresh-enrollment dossier

This is a read-only consolidation of the actual closed installation, real disabled issuer and signed broker evidence. It is **not another runtime deployment or synthetic qualification suite**. It has no apply, arm/resume, registry-enable or enrollment action.

## Run

```bash
cd ~/RB-ITOS-AI
unzip hilega-activation-dossier-v1.zip
.venv/bin/python hilega-activation-dossier-v1/prepare.py \
  --repo "$PWD" \
  --active-plan "$PWD/hilega-group2-upgrade-plan-qfgbdwft/PLAN.json" \
  --active-plan-sha256 4dc497c053d41c136559b3c4ef9918598ddc6bb1b3f5447fe89032a79456c7f5 \
  --issuer-plan "$PWD/hilega-issuer-provision-plan-396ppkpz/PLAN.json" \
  --issuer-plan-sha256 8a311eb7d12c998e854cabc38673051555564d1f7d8a5b366e51335dd7450462 \
  --evidence-review "$PWD/hilega-live-prerequisites-review-djuyjmst"
```

Uses existing pinned rollout/issuer status tools, current installed modules and signed evidence. No broker requests or package installations. Existing status tools verify live hashes and the disabled issuer without changing services or databases; private key/credential contents are never printed or copied into the dossier.

## One combined output

A private `hilega-activation-dossier-*` folder contains:

- `EXACT-BINDINGS.json`: current release/plan, issuer key fingerprint, disabled registry hash, installed wrapper/recovery files, unit definition paths and signed evidence hash/age.
- `STATE-SNAPSHOT.json`: query-only application/adapter counts, paused control/stop state, source cursor, lease/heartbeat and preparation configuration flags. Database snapshots are independent, not a cross-database atomic snapshot.
- `COMBINED-WORKFLOW.json`: ordered stages and exact prerequisites for a bounded preparation window, one natural post-resume seed, durable handoff, signed disabled enrollment, approved registry/attachment and recovery bindings, then a separate final hard-gate/live activation review. Unknown future seed/context/owner/lease fields stay null. A proposed 300-second window is a design parameter only; it is not approved or executed.
- `MILESTONES.md`: external evidence blockers separated from unfinished implementation/approval work.
- `RESULT.json`: explicitly blocked/not-live-ready summary, not a passing activation receipt.

The existing runtime must remain paused, with no pending stop, empty preparation/adapter lifecycle and disabled registration. The issuer must remain the verified disabled material. Unexpected live state or changed bound files stops the dossier rather than silently replacing bindings.

## What cannot be cleared by more synthetic passes

The earlier evidence does not establish broker timestamp semantics, final fee attribution/report finality, full contract identity or strategy ownership. Matching two historical fills by several fields is corroboration, not certification of those remaining facts. Supply Upstox's timestamp reply and a final contract note/itemized fee report privately/redacted as appropriate; do not supply keys or tokens. No support message is sent by this tool.

The live bounded-window plan/controller, exact enrollment approval, activation wrapper/supervisor/recovery bindings and final operational/gate-release qualification are also explicitly identified as remaining work. This dossier does not mislabel them as implemented or create a runnable activation plan while those bindings are unknown.

No live key is created/rotated, no issuer grant is signed, no controller is resumed, no owner is enrolled, no signal/cursor is replayed, and no database is restored. Production execution remains disabled.

No behavioral tests run locally or as part of this consolidation. Local verification is static syntax/AST and ZIP integrity only. Current status/evidence verification takes place on the VM when the command runs.
