# RB-2.0 Sprint 2 — Institutional Flow Intelligence

## Scope

Observation-only institutional intelligence built on persisted `ONLINE` option-chain snapshots.

### Added

- `oi_velocity.py` — 1/5/15-minute OI velocity, acceleration and reversal state.
- `premium_flow.py` — premium expansion, compression, decay, exhaustion and reversal expansion.
- `strike_rotation.py` — OI-weighted call/put concentration migration.
- `buy_sell_strength.py` — aggregate institutional buying/selling strength and market conviction.
- `institutional_confidence.py` — advisory Institutional Confidence Index (ICI), 0–100.
- `institutional_sprint2.py` — read-only service that combines Sprint 1 and Sprint 2 evidence from live captured option-chain snapshots.
- `ui/institutional_sprint2_panel.py` — Streamlit panel for the new metrics.
- `test_rb20_sprint2_institutional_intelligence.py` — focused Sprint 2 tests.

## Execution safety

`Execution Impact = NONE`.

Sprint 2 does not change Primary Decision Engine confidence, Opportunity Health, Committee approval, Portfolio admission, Queue behaviour or Exit Engine logic.

## UI hook

The repository baseline uploaded to GitHub contains compiled `__pycache__` for the Intelligence page but omits the corresponding `ui/pages/intelligence.py` source file. The new panel is therefore committed as a standalone component. In the complete source tree, wire it into the existing Intelligence page with:

```python
from red_bar_lab.ui.institutional_sprint2_panel import render_institutional_sprint2_panel
```

and near the top of `render_page(...)`:

```python
render_institutional_sprint2_panel(database, instrument_key)
```

## Validation

Validated against the complete RB-2.0.0 Sprint 1 source package before commit:

- Focused institutional tests: 7 passed.
- Full regression suite: 249 passed.
- Python compile check: passed.
