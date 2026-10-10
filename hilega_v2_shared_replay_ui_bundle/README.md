# V2 shared replay UI correction

This bundle targets the supplied RB-ITOS-AI-new.zip version. It connects the tested V2 alignment/dual-exit historical replay to the shared Hilega candle decision table instead of the separate custom alignment table.

Install from your project root:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
unzip -o hilega_v2_shared_replay_ui_bundle.zip
python hilega_v2_shared_replay_ui_bundle/install.py &&
./scripts/restart.sh &&
./scripts/status.sh
```

Refresh the browser after restart. Open Hilega Historical Replay and select “V2 — alignment setup + dual exit (research)”. Select any supported historical date. The existing automatic replay/cache foundation remains in place; complete local candles and prior warmup are required.

Expected flow:
1. Existing date/strategy selectors and full-session daily points summary.
2. Existing full-session / candle-by-candle / play / previous / next controls.
3. Active replay trade and completed replay trade sections in the shadow table style.
4. Shared Historical candle decision audit, with All / Armed / Entries / Exits / Continuations / Rejected / Review filters.
5. The same “View audit” expander: Nifty candle, previous/current indicators, strategy state, entry/exit, WMA strength, gap, expansion, persistence, window and dual-exit checks.
6. Existing manual review and export flow.

Select candle-by-candle mode to see an active trade and its running Nifty points at that historical checkpoint. A completed full-session replay normally has no active trade. Future exit times, prices, realized results and final excursions are not displayed as current values during stepping. Daily performance at the top is explicitly a full-session summary.

Same-time exit and entry are separate audit rows with distinct row IDs and the same actual timestamp. Exit is displayed first within that checkpoint. No artificial milliseconds or altered signal timestamps are introduced. Each row retains its own trade origin, so old trade losses and new entry zero points remain separate.

The tested strategy rules are unchanged. This bundle does not enable the tested policy in live trading or Sandbox, reconstruct option fills, fabricate PCR evidence, or alter frozen/forward-confirmation artifacts. Nifty points are index points, not option P&L. Exact option fills/PCR are marked unavailable in this research audit. Existing live and baseline option/PCR inspection remains available.

Technical scope:
- New read-only backend presentation adapter; existing replay engine/cache unchanged.
- Historical V2_ALIGN endpoint delegates through that adapter.
- Shared audit component gains optional unique row IDs, authoritative research inspection and explicit decision descriptions; baseline rows retain their existing behavior.
- New Nifty replay trade ledger uses shared shadow table styles.
- Historical page removes the custom alignment audit branch and uses the common decision table.

Validation performed: five backend presentation tests, nine automatic-replay regression tests, Python compilation, shared React rendering/lifecycle checks, and TypeScript/Vite build. The projected audits for Oct 5–9 reconcile exit counts and signed Nifty points with all five previously tested trade ledgers, including Oct 6 -50.70. No browser/VM runtime verification is claimed; refresh the installed UI and inspect the result there.

Installer checks the supplied source hashes before replacing files, accepts its own already-installed versions for repeat installation, backs up affected source and restores on failed checks. A different source version stops before installation. If frontend build starts and fails, rebuild restored frontend before restart.
