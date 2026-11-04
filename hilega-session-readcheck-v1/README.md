# Active-session read-only validation

Run a fresh account/cash snapshot using the running closed worker's existing broker read context. This is a validation command, not enrollment or activation. It does not rerun a test suite, restart services, modify databases/configuration or resume the controller.

```bash
cd ~/RB-ITOS-AI
unzip hilega-session-readcheck-v1.zip
.venv/bin/python hilega-session-readcheck-v1/check.py \
  --repo "$PWD" \
  --active-plan "$PWD/hilega-group2-upgrade-plan-qfgbdwft/PLAN.json" \
  --active-plan-sha256 4dc497c053d41c136559b3c4ef9918598ddc6bb1b3f5447fe89032a79456c7f5
```

The command verifies current closed status before and after, reuses the pinned issuer tool's running-source identity/configuration reader, and calls the existing GET-only account/cash collector against installed module bytes. Profile matching, signed account verification, normal timestamp validation, capability checks and funds schema checks remain intact. A timestamp/network/token failure is reported without bypassing the validator.

The current IST session date is derived at execution time. The summary includes broker order/trade/position counts, nonterminal orders, nonzero positions, diagnostic issue count, funds stability, source PID stability and query-only preparation/adapter table counts. Independent endpoint/database snapshots are not atomic. A current snapshot cannot guarantee state after it completes.

Your confirmation that the two **2 November** trades were manual applies to that captured activity only. Today's fills are not automatically attributed to you, Hilega or another system. Existing historical timestamp/fee/full-contract/ownership blockers remain unresolved by this check. Option quote freshness, warmup and strategy signal readiness are explicitly not certified.

Signed account/cash evidence is saved only to an owner-private new `hilega-session-readcheck-*` folder with `.gitignore`; raw credentials and keys are never printed. Paste the printed `RESULT` summary, not private capture contents. Broker requests are fixed GET-only endpoints via the existing client. Registration/registry settings are unchanged and no orders are sent.

No new runtime/deployment changes are included. The only collector difference is forwarding a safe uppercase blocked-account reason instead of hiding it behind a generic error. Local checks are static syntax/AST, preserved collector checks and ZIP integrity; no behavioral tests or live broker requests run on the development host.
