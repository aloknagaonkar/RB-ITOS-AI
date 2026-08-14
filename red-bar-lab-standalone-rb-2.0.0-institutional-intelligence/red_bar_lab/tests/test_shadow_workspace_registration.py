from pathlib import Path


def test_workspace_registers_shadow_directional_page():
    page = Path("red_bar_lab/ui/workspace.py").read_text(encoding="utf-8")

    assert "shadow_directional_diagnostics," in page
    assert '"Shadow Directional": shadow_directional_diagnostics' in page
    assert '"Shadow Directional"' in page
    assert "AttributionAwarePaperAutomationService" in page
