HILEGA UPSTOX BROKER PREFLIGHT V1

This bundle installs an isolated broker-plumbing validator.

It provides:
- live Upstox profile checks that are strictly read-only;
- an Upstox Sandbox-only place/modify/cancel roundtrip;
- bullish -> CE and bearish -> PE validation;
- LIMIT-only orders and explicit SANDBOX_ONLY confirmation;
- tests proving no live order method is present.

It does not enable paper trading, change Hilega strategy rules, select quantity,
change exits, restart services, or submit live orders.

Install:
  source .venv/bin/activate
  python hilega_upstox_broker_preflight_bundle/install.py

Then read:
  docs/strategies/HILEGA_UPSTOX_BROKER_PREFLIGHT_V1.md
