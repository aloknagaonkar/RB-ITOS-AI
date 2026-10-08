Hilega PCR observation panel

Install from repository root with the virtual environment active:
python hilega_pcr_ui_bundle/install.py
./scripts/restart.sh
python hilega_pcr_ui_bundle/enable_collection.py

The setup command uses current Hilega expiry, Upstox provider and ±5 wings. It retains existing anchor time (default 09:20 IST), interval and thresholds; creates a new PCR configuration only when needed, then enables collection. It calls local configuration APIs only. This does not enable orders or change V2 entry/exit rules.

Both ranges are shown in Hilega shadow below expiry information. Fixed ATM is captured at the configured morning anchor; moving ATM follows spot. Each mode uses its existing collector range, not an arbitrary slice of available contracts. PCR is sum PE OI / sum CE OI. Strike PCR is PE OI / CE OI. Price and observed OI comparisons use existing 5/15/30-minute positioning engine. Missing denominator/baseline or mismatched observation is unavailable. Hover OI change for previous/current OI.

Coverage, provider, collection flag, worker, expiry and receipt age are visible. Fixed range can remain unavailable before anchor. Baselines require elapsed observations. Refresh is every 15 seconds. Older data retained after a refresh failure is explicitly marked potentially stale. Review receipt age and collection health.

PCR has a separate expiry configuration: this command synchronizes it once, not automatically every day. Re-run setup when expiry changes. Collector and broker data must be validated on the VM tomorrow. No profitability inference from a build-up label.

Validation: TypeScript/Vite build passed; existing positioning tests 36 passed. No external broker calls performed during development.
