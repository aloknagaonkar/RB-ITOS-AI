HILEGA UPSTOX SANDBOX EXECUTION V1

Installs a disabled-by-default, manually invoked Hilega-to-Upstox Sandbox adapter.

Safety:
- Never uses the Upstox live order API.
- Does not read UPSTOX_TRADING_ACCESS_TOKEN.
- Does not modify or connect the live Hilega worker.
- Requires an explicit sandbox gate, disabled kill switch and SANDBOX_ONLY confirmation.
- Allows exactly one dynamically resolved option lot.
- Journals REQUESTED and ACCEPTED states and prevents duplicate event submission.

Install:
  source .venv/bin/activate
  python hilega_upstox_sandbox_execution_bundle/install.py

After installation, read:
  docs/paper/HILEGA_UPSTOX_SANDBOX_EXECUTION_V1.md

Do not enable unattended sandbox execution in this phase.
