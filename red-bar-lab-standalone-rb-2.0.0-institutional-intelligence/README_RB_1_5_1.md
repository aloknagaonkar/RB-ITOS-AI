# RB-1.5.1 — Option Chain Sync Validation + Live-Parity Historical Replay

This release does not change live trading rules. It strengthens historical validation.

## New
- Historical expired-option contract discovery and one-minute OHLC/volume/OI cache.
- Option Chain Sync Validator with contract, CE/PE, candle timestamp-gap and OI coverage.
- Replay readiness labels: `PARTIAL_LIVE_PARITY_HIGH`, `PARTIAL_OPTION_REPLAY`, `UNRELIABLE_OPTION_REPLAY`.
- Historical bid/ask, IV and Greeks are explicitly unavailable and are never fabricated.
- When option coverage is replay-ready, Historical Decision Replay uses the same production policy engines for:
  - Primary candidate scoring formula
  - Opportunity Health
  - Performance Selection
  - Institutional Execution Committee (Shadow remains informational only)
  - Portfolio Risk Manager / multi-candidate admission
  - Paper Exit Engine (SL, BE, trailing, technical/thesis, target, EOD)
- Replay table now exposes candidate rank/score, Opportunity Health, portfolio admission/watchlist reason, option entry/exit, return and exit reason.

## Important fidelity note
Expired-option historical candles do not contain historical order-book bid/ask depth, IV or Greeks. Spread and liquidity are therefore explicit neutral replay priors and the replay is labelled partial live parity, never full microstructure parity.
