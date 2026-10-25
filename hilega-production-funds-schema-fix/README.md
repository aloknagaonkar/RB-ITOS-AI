# V3 funds: optional pledge total correction

Root cause verified from the live response's field/type listing: the V3 response
contains data.available_to_trade.cash_available_to_trade.total and cash margin
used, but omits data.available_to_trade.pledge_available_to_trade.total. The old
parser incorrectly required that optional net pledge value for cash observation.

Changes:
- Cash and cash margin used remain mandatory, finite numeric values.
- Missing/null net pledge total becomes unavailable, not zero and not a derived
  value. No pledged collateral is added to cash or to the 50% preview.
- The 50% preview still uses net cash only, rounded down to paise. No fallback to
  total margin, opening balance or zero cash. Allocation remains unapproved.
- Detailed allowlisted validation errors survive the cached UI response.
- Added fixtures for the observed schema (no amounts from the user's account),
  missing cash, invalid pledge values, cache/display round-trip and error display.

Only the broker observation module and its tests change. No strategy files,
controls, execution transports, credentials or frontend source are modified.
No tests or builds were run in the preparation environment; Python syntax was
checked. Run staged validation on your VM before applying.

```bash
cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-funds-schema-fix.zip
.venv/bin/python hilega-production-funds-schema-fix/install.py \
  --stage data/research/hilega-funds-schema-stage
.venv/bin/python hilega-production-funds-schema-fix/validate.py \
  --stage data/research/hilega-funds-schema-stage \
  --output data/research/hilega-funds-schema-validation.json
```

After PASS:

```bash
.venv/bin/python hilega-production-funds-schema-fix/install.py --apply \
  --validation data/research/hilega-funds-schema-validation.json
```

After APPLIED:

```bash
bash scripts/restart_hilega_ui_api_safe.sh
```

The installer backs up originals, requires exact known hashes, and will refuse
modified targets. It does not restart services or submit orders. The API restart
retains the existing strategy worker and re-pauses the simulation workspace.
Continuous read-only collection must already be enabled via
HILEGA_PRODUCTION_BROKER_OBSERVE=1. Wait for a new snapshot, normally within
30 seconds plus network time. The UI polls automatically; no frontend rebuild
is necessary because frontend source has not changed.

Expected: funds PASS, cash and 50% preview displayed, pledged margin Unavailable
if absent. Check the cash against the same account in Upstox. Production remains
disabled; successful funds parsing is not approval for order allocation.

Do not upload snapshots, .env files or access/control tokens to Git or chat.
