# Historical Replay Audit Readability V1.1

Presentation-only enhancement for the Historical Replay page.

Changes:
- merges step-audit rows and lifecycle events into one chronological progression
- sorts same-time events in strategy order
- surfaces futures alignment, spot classification, exact option, entry and exit summary
- displays OHLC for option-minute events when present
- displays stop / BE / trail / MFE / MAE for risk updates when present
- displays exit reason / exit price / gross / net / MFE / MAE when present
- keeps raw observation IDs visible for audit traceability

No strategy rules, replay rules, event generation, risk rules, data files, or backend
endpoints are modified.
