# Hilega-Milega Live Shadow UI V2

## Purpose
Align the Hilega-Milega page with the existing Live Shadow operational page and keep technical indicator detail inside the Audit view.

## Changes
- Front page now focuses on operational lifecycle information:
  - current strategy state
  - last entry detected
  - last exit
  - entry/exit activity table
  - route/state/underlying price
  - option-shadow lifecycle status
  - exit price/reason
- Removed Close / RSI / EMA3 / WMA21 columns from the front activity table.
- RSI/EMA3/WMA21, previous values, condition checks, Route A/Route B reasons, option candidate/snapshot/lifecycle data, transitions, and hash-chain details remain in Detailed Audit.
- Detailed Audit is now a right-side panel on desktop, matching the Live Shadow page structure more closely.
- Clicking Audit immediately displays the report already loaded in the audit index, then hydrates it from `/audit-detail`. This prevents the UI from appearing to do nothing if the detail request is slow or fails.
- Audit errors are surfaced in the page banner.
- On narrower screens the audit panel moves below the activity table.

## Files
- `frontend/src/hilegaMilegaShadow.tsx`
- `frontend/src/liveShadow.css`

## Apply
Copy the two files over the same paths in the repository.

## Validate
```bash
cd ~/RB-ITOS-AI/frontend
npm run build
```

Then restart/reload the frontend and check the Hilega Shadow tab.

## UI smoke checklist
- Strategy state card visible.
- Last Entry Detected card visible.
- Last Exit card visible.
- Main table does NOT show Close / RSI / EMA3 / WMA21 columns.
- Entry rows show `ENTRY DETECTED`.
- Exit rows show `EXIT`, exit price and reason.
- Audit button opens the right-side Detailed Audit panel.
- Detailed audit includes indicators, Route A/B reasons, ATM±2 legs, transitions, and audit integrity.
