from market_lab.midpoint_strategy import live_shadow_ui as ui


def test_endpoint_defaults_are_plain_ints(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "AUDIT_PATH", tmp_path / "missing.jsonl")
    assert ui.events()["count"] == 0
    assert ui.timeline()["count"] == 0
