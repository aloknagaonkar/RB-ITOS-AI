# Warmup tail repair

Run on the VM: `.venv/bin/python hilega-warmup-tail-repair-v1/repair.py --repo "$PWD" --session 2026-10-30 --repair`

Runs the included tests on the VM before repair. Fetches fixed Upstox V3 historical GET endpoints; requires 375 exact minutes, unchanged overlapping values, and the installed native 75-bar validator. Incomplete data or changed source pins blocks replacement. Original bytes are retained in the reported private audit directory. No application source or service changes. No orders. Credentials are read from an owned private .env (or explicit --env-file), never printed. After success check the warmup alert on the next worker poll. Tests have not been executed locally.
