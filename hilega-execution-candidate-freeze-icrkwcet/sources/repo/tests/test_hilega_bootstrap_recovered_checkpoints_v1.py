from pathlib import Path

def test_bootstrap_recovery_source_contract():
    s=Path("backend/market_lab/hilega_milega_live_shadow_v1.py").read_text(encoding="utf-8")
    assert "CURRENT_SESSION_BOOTSTRAP_REPLAY" in s
    assert "BOOTSTRAP_RECOVERED_CHECKPOINT" in s
    assert "bootstrap_recovered" in s
    assert "existing_decision_checkpoints" in s
    assert "recovered_checkpoint_count" in s
    assert "self.strategy.audit_store = collector" in s
    assert "self.strategy.audit_store = self.step_audit" in s
