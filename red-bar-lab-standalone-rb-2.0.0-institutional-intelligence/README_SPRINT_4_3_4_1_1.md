# Sprint 4.3.4.1.1 — Restore Shadow Directional Workspace Navigation

The Sprint 4.3.4.1 attribution-hook package replaced `workspace.py` with a
version that preserved the attribution-aware Paper Trading service but omitted
the Shadow Directional page import and navigation registration.

This fix restores:

- `shadow_directional_diagnostics` import;
- `Shadow Directional` in `_PAGE_MODULES`;
- `Shadow Directional` in the Workspace sidebar list;

while retaining:

- `AttributionAwarePaperAutomationService`;
- Paper Trading wrappers;
- all existing Workspace pages from Sprint 4.3.4.1.

## Files

- replacement `red_bar_lab/ui/workspace.py`
- `red_bar_lab/tests/test_shadow_workspace_registration.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_shadow_workspace_registration.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```

Restart Streamlit after replacing the file.
