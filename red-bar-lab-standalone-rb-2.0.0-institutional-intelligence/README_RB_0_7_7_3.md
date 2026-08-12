# RB-0.7.7.3 — Top-5 Table + Reliable Candidate Selector

This release simplifies candidate inspection.

## UI

1. Top-5 ranked candidates remain visible in one comparison table.
2. A `Select Candidate to Inspect` dropdown appears directly below the table.
3. Selecting Rank #1-#5 stores the exact option symbol.
4. The detail pane resolves that same symbol and updates:
   - Rank / contract
   - Rule score
   - Candidate Health
   - Entry / Stop / Targets
   - Score breakdown
   - Greeks
   - Why Rank #1 / Why Not Rank #1
   - Selected option candle
5. A visible `DETAIL PANEL: Rank #N · <symbol>` banner confirms the exact
   contract being displayed.

## Safety

Rank #1 remains the only automatic execution candidate.
Rank #2-#5 selection is inspection-only.
