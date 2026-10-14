# Sandbox-linked five-strike view

Install from RB-ITOS-AI root:

```bash
python hilega_sandbox_five_strike_view_bundle/install.py
```

Refresh the Hilega page after PASS. The new section is titled "Sandbox signal · five-strike comparison", below completed Sandbox trades. It reads the existing directional trade-dashboard and Sandbox dashboard every ten seconds, with a timeout and stale banner. No worker restart or re-arm is needed for this view.

The small backend fix preserves completed order pairs even when a price is missing. An API restart is required to load that fix. You can defer your standard service restart until a suitable point; the five-strike frontend itself works against the existing API. After any general restart, check Sandbox worker status separately; do not re-arm unnecessarily.

For each shadow signal in the Sandbox selected session, display five fixed roles: ATM-2, ATM-1, ATM, ATM+1, ATM+2. Missing legs remain visible. Entry premium/time, current or exit premium/time, estimated premium points/return, MFE/MAE, and hypothetical rupee P&L are included. Hypothetical rupee values use the matched Sandbox quantity as a comparison quantity and are unavailable when no Sandbox submission is uniquely matched.

Exactly one contract remains submitted to Sandbox. Match the shadow lifecycle using direction, expiry and signal boundary/bar timestamp, then match the selected leg by exact instrument key. Ambiguous/no matches are never guessed. Selected rows show existing BUY/SELL order IDs and separate Sandbox order-time quote P&L, which can differ from shadow candle-open prices.

The other four rows are OBSERVATION ONLY and submit no orders. Five-strike hypothetical P&L is not added to account total. Neither quote-based completed P&L nor accepted order acknowledgements prove confirmed fills. The existing account summary remains selected-contract estimates only.

This is the display change agreed in the prior explanation, not a five-contract execution change. It does not increase the four-order session cap, change quantity, arm/disarm, alter exit rules or submit historical missed signals. The EMA10 experiment stays offline.

Validation: Node model checks verify five rows, unique identity, ambiguity handling, missing-exit exclusion, positive/negative long-PE P&L and missing quantities. Existing Sandbox dashboard tests and TypeScript/Vite build are run by the installer. Source backups and rollback are included. No live VM or browser visual verification was performed locally.
