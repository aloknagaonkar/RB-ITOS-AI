HILEGA SANDBOX EVENT BRIDGE V1

Installs the disabled-by-default observation bridge between genuine Hilega
directional audit events and the already validated Upstox Sandbox adapter.

This phase records WOULD_SUBMIT only. It cannot call Upstox.

Install:
  source .venv/bin/activate
  python hilega_sandbox_event_bridge_bundle/install.py

No restart is required. No live or sandbox order is sent.
