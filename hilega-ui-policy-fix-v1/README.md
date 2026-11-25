# Hilega UI policy timeline correction

Fixes the observed candle table showing NO_SIGNAL while backend owner is BEARISH.

The candle API previously preferred older PROCESSED rows over newer-policy
RECOVERED rows at the same timestamp, mixing 3.0.0 entries/exits with 3.0.2
continuations. It now selects one recorded policy version per session before
applying processed/recovered precedence. Superseded journal evidence is retained.

The frontend previously mapped owner BEARISH to state_after BEARISH, while its
classifier requires BEARISH_ACTIVE. It now uses the existing directional state
mapper, carries version/provenance, and keeps entry references across the same
policy only. Reconstructed underlying entry references are visibly labelled and
are not presented as newly opened option trades.

## Prepare on the VM

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -u -B hilega-ui-policy-fix-v1/prepare.py --prepare
```

This performs exact source guards, creates an isolated /tmp candidate, runs
Python/JavaScript contract tests, builds the frontend and verifies the companion
runtime pins. It does not install files or restart services. Paste the terminal
result and any failing log. A successful result includes the exact candidate and
asset hashes needed for the controlled installation step. No installer is
included at this stage; do not manually copy candidate files over the live app.

Existing frontend dependencies are reused by a staging symlink; no npm install
or package upgrades are performed. Builds and generated outputs remain in the
isolated stage. Original app files, raw journals, caches, databases and broker
controls remain untouched. The collector and observation workers keep running.

## Reviewed changes

* backend/market_lab/hilega_directional_candle_ui_v1.py — display policy selection
  and evidence provenance only; no strategy signal calculation changes.
* frontend/src/hilegaDirectionalAuditOverlay.ts — normalised active-state labels,
  state fields and version/provenance.
* frontend/src/hilegaDecisionTable.tsx — version-separated entry reference and
  visible reconstructed-reference label.
* Three companion integrity files — one reviewed runtime hash change and its
  manifest/CLI anchors. The other 415 runtime pins and all authority flags remain
  unchanged. These anchors must be installed together with the API correction.

## Verification

Local checks cover new-policy recovery surviving older processed evidence,
same-policy precedence, session boundaries, manual-reset version separation,
immutable inputs, both directional active labels, reconstructed entry points,
orphan-state protection, and policy-version separation. Full frontend typecheck
and build are mandatory on the isolated VM candidate before installation.

This corrects the live candle view. It does not rewrite historical journal
records, change live/replay entry or exit rules, fabricate option fills or alter
broker execution settings.
