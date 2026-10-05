HILEGA UPSTOX SANDBOX LIVE WORKER V1

Installs a standalone, session-armed worker that submits only new genuine
Hilega events to Upstox Sandbox.

Prerequisites:
- Hilega Upstox Sandbox execution V1 installed.
- Hilega Sandbox Event Bridge V1 installed.

Install:
  source .venv/bin/activate
  python hilega_upstox_sandbox_live_worker_bundle/install.py

The installer does not arm or start the worker and sends no order.
