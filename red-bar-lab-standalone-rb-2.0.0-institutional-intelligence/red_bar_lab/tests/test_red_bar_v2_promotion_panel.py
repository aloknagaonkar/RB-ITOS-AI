from types import SimpleNamespace

from red_bar_lab.services.red_bar_v2_promotion_readiness import (
    PromotionStage,
    evaluate_promotion_readiness,
)
from red_bar_lab.ui.red_bar_v2_promotion_panel import (
    _automatic_evidence,
    _default_evidence,
    _stage_message,
    build_red_bar_v2_promotion_wrapper,
)


def test_default_ui_evidence_preserves_validated_test_baseline():
    evidence = _default_evidence()
    assert evidence.unit_tests_passed == 88
    assert evidence.unit_tests_failed == 0
    assert evidence.feature_flag_default_off is True
    assert evidence.legacy_exit_path_unchanged is True


def test_default_ui_evidence_remains_fail_closed_without_operational_data():
    report = evaluate_promotion_readiness(_default_evidence())
    assert report.stage == PromotionStage.NOT_READY
    assert report.execution_enablement_allowed is False
    assert "REPLAY_COVERAGE" in report.blocking_codes
    assert "PARITY_BASELINE" in report.blocking_codes
    assert "SHADOW_OBSERVATION" in report.blocking_codes


def test_automatic_evidence_without_settings_is_safe_default():
    evidence = _automatic_evidence(None)
    assert evidence.unit_tests_passed == 88
    assert evidence.replay_sessions == 0
    assert evidence.shadow_sessions == 0


def test_stage_messages_do_not_authorize_live_execution():
    level, message = _stage_message(PromotionStage.PAPER_READY)
    assert level == "success"
    assert "Live broker execution is not authorized" in message


def test_wrapper_renders_panel_before_existing_research_page(monkeypatch):
    calls = []

    def panel(_st, settings=None):
        calls.append(("panel", settings))

    def original(*args):
        calls.append(("original", args[0]))
        return "done"

    monkeypatch.setattr(
        "red_bar_lab.ui.red_bar_v2_promotion_panel.render_red_bar_v2_promotion_panel",
        panel,
    )

    import sys

    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace())
    settings = object()
    wrapped = build_red_bar_v2_promotion_wrapper(original)
    result = wrapped(settings, None, None, None, None, None, None)

    assert result == "done"
    assert calls == [("panel", settings), ("original", settings)]
