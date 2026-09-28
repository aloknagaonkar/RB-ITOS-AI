MIDPOINT M2.3 — INLINE INSPECT EXPANDER

Apply from ~/RB-ITOS-AI:
  python /tmp/midpoint_m2_3/scripts/apply_midpoint_m2_3_inline_inspect_expander.py

Check:
  python /tmp/midpoint_m2_3/scripts/check_midpoint_m2_3_inline_inspect_expander.py

Build:
  cd frontend
  npm run build

Then hard refresh:
  Ctrl+Shift+R

This is frontend-only. No API restart is required if the API is already healthy.
Do not restart live_shadow_worker_v1.
