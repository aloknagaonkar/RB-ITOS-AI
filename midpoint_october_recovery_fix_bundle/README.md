# October Midpoint recovery downloader correction

The legacy September downloader resolved the September 29 expired future even
when only October dates were requested. This incorrectly blocked October 6/7.
The correction applies that guard only for requested September 9–29 dates.
October dates use the existing date-aware active/expired futures resolver.
Provider responses still determine the instrument and expiry; nothing is hardcoded
for October, and missing contracts/coverage still fail closed.

Four local regression tests passed: October bypass, September missing-contract
rejection, mixed-date resolution, wrong September expiry rejection.
Real October futures acquisition remains to be run on the VM.

```bash
source .venv/bin/activate
python midpoint_october_recovery_fix_bundle/install.py
PYTHONPATH=backend:. python scripts/materialize_midpoint_forward_market_data.py \
  --dates 2026-10-06 2026-10-07 --broker-only \
  --output-root data/recovery/october-2026/midpoint
```

No restart needed. Only downloader/test source changes. Entry/exit rules, live
audits, frozen evidence, sandbox dispatch and orders are unchanged.
October metadata is labeled HISTORICAL_MARKET_RECOVERY, not September OOS.
The downloader stages both dates before publishing and refuses an existing output
directory. If it already exists, stop and inspect it; do not delete recovery data
blindly. The previous failure occurred before directory creation.

Expected successful validation: 360 paired minutes per date, 09:15–15:14 IST,
with exact NIFTY and futures coverage and positive futures volume. Output prints
each resolved futures instrument and expiry. Verify these before replay.
NIFTY's separate 375-minute recovery does not need rerunning.
