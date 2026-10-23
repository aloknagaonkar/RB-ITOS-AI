# Recorded same-boundary reversal UI repair

Uploaded Oct23 source classifies entry before exit, then flags the new entry
while the old position is active, leaving old entry price/direction in lifecycle
state. Raw13:05audit proves bearish exit at22429.35from22637.95(+208.60), followed
by bullish entry22429.35. This patch displays recorded current-checkpoint exit
and entry as two distinct rows before computing lifecycle/P&L. No exit is inferred
from a mere opposite entry, and future linked exits do not split an entry row.

UI-only shared decision table: applies wherever this component is used (live and
replay). No backend event journal rewrites, strategy changes, orders or repair of
broker positions. Full raw audit confirms strategy events, not broker execution.
If current API omits exit transition entirely, patch intentionally retains review
rather than fabricating an exit. Obtain API payload to diagnose that case.

Installer verifies exact uploaded source and payload hashes; backups before apply.
VM: python install.py, then --apply, node tests/hilega_reversal_ui_vm.cjs, npm
--prefix frontend run build. No tests/builds run locally per user preference.
After successful build use existing scripts/restart_hilega_ui_api_safe.sh; do not
restart strategy worker or re-arm execution for this presentation repair.

Expected13:05two rows: BEARISH EXIT+208.60then BULLISH ENTRY0.00.13:10bullish mark
at22400.45is-28.90. Existing unmatched entry review and linked future-exit rules
must remain. Test uses fixture projection of real event evidence; browser/API
verification is still required after install. Read recorded audit remains intact.
