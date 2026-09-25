Hilega Directional Audit UI Patch

Purpose:
- Direction-aware bullish/bearish audit labels
- PE labels for bearish, CE labels for bullish
- Previous RSI/EMA/WMA values for directional-only rows
- Route-aware audit wording/validation
- Frontend-only: no strategy, API, worker, entry or exit logic changes

Usage from repo root:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python /path/to/apply_directional_audit_fix.py

Then:

  cd ~/RB-ITOS-AI/frontend
  npm run build

Verify bundle:

  grep -oE '/assets/[^\"]+\.(js|css)' dist/index.html
  curl -sS http://127.0.0.1:8123/ | grep -oE '/assets/[^\"]+\.(js|css)'

Then hard refresh browser with Ctrl+Shift+R.

No API or worker restart is required.
