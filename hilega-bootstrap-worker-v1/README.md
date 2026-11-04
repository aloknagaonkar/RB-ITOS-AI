# Combined closed-worker integration and restart qualification

This candidate connects the previously validated disabled handoff to the **actual bundled worker launcher**. It handles the launcher's `Bridge` input by reopening an existing guarded preparation Source; it does not baseline or consume the strategy journal. With no explicit handoff configuration, existing default dispatch is retained.

The configured local-review path requires a pinned private configuration, an independent pinned signing root, a short-lived signed mailbox, the completed signed handoff receipt, the current source lease, unchanged private identities, a paused controller and the real hard order gate closed. Each poll revalidates these bindings. A missing mailbox waits while paused. A stale lease, changed file, bad signature or expiry stays paused. A restart requires an explicit newly signed handoff/mailbox; it never silently migrates ownership.

**This is closed handoff admission, not an enabled execution factory.** No production token provider, order transport, live enrollment or automatic boot rebinding is configured. The separate factory registration remains disabled. Capacity stays one; premium and daily loss caps remain null.

## Single VM check

```bash
cd ~/RB-ITOS-AI
unzip hilega-bootstrap-worker-v1.zip
.venv/bin/python hilega-bootstrap-worker-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-6ol7neof/PLAN.json" \
  --current-plan-sha256 c57d04cfb8e2492f63c6eccff7ebcb43fa29c4cd99cca36c17f9425ed615d9b6 \
  --handoff-review "$PWD/hilega-bootstrap-handoff-review-nz9r_xwk"
```

Requires the unchanged earlier packages: worker-qualification v1, combined v2, local-bootstrap v2 and bootstrap-handoff v1, their passed review folders, pytest in the VM venv and user systemd. Installs no packages.

The one disposable systemd unit runs **36 cases**: 19 existing bootstrap, 13 existing handoff, 3 new worker checks and one seed preflight. The new process checks execute the exact candidate launcher with synthetic clock injection and disposable databases. They exercise signed admission, SIGKILL/restart with stale-lease rejection, explicit rebinding and tampered mailbox rejection. The third check confirms no opt-in selects unchanged default dispatch. Real network calls are denied by Python hooks and the systemd address-family restriction.

The fixture supplies an already prepared synthetic seed and context. It does not establish fresh real market evidence or certify the configured execution-factory lifecycle. The synthetic clock is frozen to keep prior seed/context valid; this is never used in the live service.

## Outputs and deployment boundary

Creates a private `hilega-bootstrap-worker-review-*` folder with `TESTS.xml`, `MANAGED-PROCESS.json`, before/after installed status, a sealed candidate, `RESULT.json`, updated `MILESTONES.md` and a hashed `DEPLOYMENT-PROPOSAL.json` with the current release as rollback target. Success files are written only after all 36 checks and installed status checks pass.

The proposal is **not an executable apply plan**. Exact wrapper/recovery bindings, quiescent backups and rollback verification remain necessary before a closed deployment. No application services are stopped/restarted and no live configuration/database is changed by this check. Disposable unit control and database writes are confined to the rehearsal.

No behavioral tests were run on the development host, following your preference. Only static syntax, source-contract and ZIP checks were performed. Paste the VM result before treating this candidate as qualified.
