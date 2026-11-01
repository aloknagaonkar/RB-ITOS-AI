from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "scripts" / "validate_hilega_milega_bullish_today_v1.py"
spec = importlib.util.spec_from_file_location("hm", P)
hm = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(hm)


def test_rsi_is_bounded_and_rising_series_reaches_100():
    x = [float(i) for i in range(40)]
    r = hm.pine_rsi(x, 9)
    vals = [v for v in r if v is not None]
    assert vals
    assert all(0 <= v <= 100 for v in vals)
    assert vals[-1] == 100.0


def test_wma_uses_recent_value_with_highest_weight():
    w = hm.wma_optional([1.0, 2.0, 3.0], 3)
    assert abs(w[-1] - (1*1 + 2*2 + 3*3)/6) < 1e-12


def test_bullish_requires_rsi_cross_above_ema_and_both_above_wma(monkeypatch):
    # Synthetic indicator arrays force exactly one valid cross at index 1.
    series = [
        (datetime(2026,9,21,10,0,tzinfo=timezone.utc), 100.0),
        (datetime(2026,9,21,10,5,tzinfo=timezone.utc), 101.0),
    ]
    monkeypatch.setattr(hm, "pine_rsi", lambda closes, length=9: [49.0, 55.0])
    monkeypatch.setattr(hm, "ema_optional", lambda vals, length: [50.0, 53.0])
    monkeypatch.setattr(hm, "wma_optional", lambda vals, length: [48.0, 51.0])
    rows = hm.detect_signals(series, "2026-09-21")
    assert len(rows) == 1
    assert rows[0]["rsi_crossed_above_ema3"] is True
    assert rows[0]["rsi_above_wma21"] is True
    assert rows[0]["ema3_above_wma21"] is True


def test_no_signal_if_ema3_is_not_above_wma21(monkeypatch):
    series = [
        (datetime(2026,9,21,10,0,tzinfo=timezone.utc), 100.0),
        (datetime(2026,9,21,10,5,tzinfo=timezone.utc), 101.0),
    ]
    monkeypatch.setattr(hm, "pine_rsi", lambda closes, length=9: [49.0, 55.0])
    monkeypatch.setattr(hm, "ema_optional", lambda vals, length: [50.0, 50.5])
    monkeypatch.setattr(hm, "wma_optional", lambda vals, length: [48.0, 51.0])
    assert hm.detect_signals(series, "2026-09-21") == []
