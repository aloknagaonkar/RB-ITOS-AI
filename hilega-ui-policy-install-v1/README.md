# Install the VM-validated Hilega UI correction

Use the already prepared candidate:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -u -B hilega-ui-policy-install-v1/install.py \
  --stage /tmp/hilega-ui-policy-fix-v1/candidate-op4vmtkk --apply
```

The installer checks the exact six source hashes and 16 built-asset hashes from
the reviewed VM preparation result. It does not rebuild or substitute a different
candidate. If the stage is missing or a source/build changed, it stops before
installation. Optional `--check` runs preflight without installing or restarting.

It verifies observation-only API settings, the existing runtime pins, reference
service identity and candidate startup checks. It creates a backup and receipt in
`data/deployments/hilega-ui-policy-fix-<timestamp>` before stopping only:

* hilega-api.service
* hilega-lifecycle-reference.service

The six reviewed source/pin files are installed together with the 16 validated
assets. Existing hashed assets remain available for previously opened browser
tabs; the entry index is installed last. The installer verifies source hashes,
runtime pins and reference startup checks again before starting the two services.
Then it verifies the current API, single-version candle timeline, reconstructed
provenance and every served frontend asset. The collector, production-source
worker, observation analytics and readiness services are never stopped/restarted
by this installer; their identities are checked for unexpected changes.

Strategy version remains `bullish-gap2-full-wma2-3.0.2-3m-bounded-warmup`.
Strategy entry/exit rules, credentials/settings, journals and databases are not
edited. Checks do not read broker credentials or submit broker requests. Normal
observation services resume their existing roles after restart.

On failure, the installer restores its attempted source/asset changes from the
backup and restarts the original API/reference services. It will not overwrite a
concurrent edit: a changed rollback lease produces ROLLBACK_REQUIRES_ATTENTION
with the exact path and backup location instead. All receipts are saved locally.

Successful status is `UI_POLICY_FIX_DEPLOYED_API_VERIFIED`. This confirms the
served API/assets, not a visual browser inspection. Hard-refresh the UI with
Ctrl+F5 and inspect the candle table. With a matching active owner it should show
directional continuation, the reconstructed-entry label, and NIFTY points from
the same-policy reconstructed entry reference. It does not create an option
trade retroactively. Rows without an entry reference remain review-required.

Paste the installation output and a refreshed screenshot to finish verification.

## Installer tests

```bash
.venv/bin/python -B -m unittest discover -s hilega-ui-policy-install-v1/tests
```

Ten local tests cover exact prepared-build validation, source/asset/report
tampering, unexpected assets, symlink refusal, successful installation with old
assets preserved, failure rollback, partial-write rollback and refusal to
overwrite a concurrent source edit. Tests use temporary fixture repositories and
mock service/API controls; they do not operate the VM services.
