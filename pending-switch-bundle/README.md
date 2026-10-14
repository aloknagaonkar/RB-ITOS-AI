# Pending opposite direction switch

Run from RB-ITOS-AI after extracting this directory:

```bash
.venv/bin/python pending-switch-bundle/apply.py
HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=1 PYTHONPATH=backend:. .venv/bin/python -m pytest -q tests/test_hilega_pending_opposite_switch_v1.py tests/test_hilega_alignment_dual_exit_live_v1.py tests/test_hilega_five_minute_setup_timing.py
bash scripts/restart.sh
```

When no actual position is open, a newly accepted opposite canonical arm cancels the old pending setup and watches the new side. An arm alone cannot enter. A confirmed opposite setup cancels the old setup and starts a fresh confirmation window with persistence reset. Another opposite accepted arm can change an arm-only watch again. Confirmed canonical setups take priority over unconfirmed arms on the same boundary. Existing completed-five-minute setup detection, minute strength/gap confirmation, exits and cutoff remain in use. The ten-minute watch expires if no setup confirms.

Live and replay use the shared gate. Decision audit and candle drilldown expose Pending direction switch records. No past orders or fills are rewritten. This is an entry policy change; focused regression tests verify behavior, profitability has not been validated. October 13's supplied 10:20–10:30 audit has no accepted opposite bullish arm, so it does not demonstrate a switch trigger.

Installer validates all three source hashes before changing anything and backs up sources and environment. Disable by setting HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED=0 in .env and restarting. Restore source copies from the printed backup to remove the patch.
