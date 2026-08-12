# RB-1.3.1 — Historical Decision Replay Validation Harness

Adds a Research Lab Historical Decision Replay section that answers the live-style question for each historical confirmed Red Bar: WOULD_TAKE, WOULD_WAIT, or WOULD_BLOCK.

Key properties:
- point-in-time only: decision metrics use candles available at the confirmation timestamp;
- no EOD option data is injected into intraday decisions;
- Primary confidence, Shadow advisory state, agreement adjustment, final confidence and expectancy are shown;
- lifecycle/session state and exact blocker/reason are visible;
- future candles are used only after the decision to label the eventual underlying outcome;
- missing intraday option microstructure/Greeks are marked neutral and surfaced as a replay fidelity limitation.

This is a validation harness, not a claim of full option-tick reconstruction. Where historical option bid/ask/Greeks were not captured, the report says so explicitly.
