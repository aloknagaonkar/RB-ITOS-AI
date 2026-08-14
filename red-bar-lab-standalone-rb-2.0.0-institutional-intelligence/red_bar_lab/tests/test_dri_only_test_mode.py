from red_bar_lab.execution.directional_regime_native_signal import (
    DirectionalNativeSignalDatabaseProxy,
)


class FakeDatabase:
    def read_signal_attempts(self, *args, **kwargs):
        return [{
            "signal_id": "REF-1",
            "direction": "BULLISH",
            "confirmation_timestamp": "2026-08-14T10:00:00",
        }]

    def read_paper_execution_orders(self, *args, **kwargs):
        return []


def test_reference_signals_enabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(
        "RB_ENABLE_REFERENCE_LEVEL_SIGNALS",
        raising=False,
    )
    proxy = DirectionalNativeSignalDatabaseProxy(
        FakeDatabase(),
        runs_root=tmp_path,
    )
    rows = proxy.read_signal_attempts()
    assert [row["signal_id"] for row in rows] == ["REF-1"]


def test_reference_signals_disabled_in_dri_only_mode(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "RB_ENABLE_REFERENCE_LEVEL_SIGNALS",
        "false",
    )
    proxy = DirectionalNativeSignalDatabaseProxy(
        FakeDatabase(),
        runs_root=tmp_path,
    )
    assert proxy.read_signal_attempts() == []


def test_explicit_setting_overrides_environment(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "RB_ENABLE_REFERENCE_LEVEL_SIGNALS",
        "false",
    )
    proxy = DirectionalNativeSignalDatabaseProxy(
        FakeDatabase(),
        runs_root=tmp_path,
        enable_reference_signals=True,
    )
    rows = proxy.read_signal_attempts()
    assert [row["signal_id"] for row in rows] == ["REF-1"]
