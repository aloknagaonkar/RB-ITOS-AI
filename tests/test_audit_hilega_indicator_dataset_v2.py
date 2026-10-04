import importlib.util
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hilega_audit_v2", ROOT / "scripts/audit_hilega_indicator_dataset_v2.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
IST = ZoneInfo("Asia/Kolkata")


def _cache(path: Path, day: date, offset: float = 0.0):
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15)
    candles = []
    for index in range(375):
        stamp = start + timedelta(minutes=index)
        close = 22000 + offset + index * 0.05 + ((index % 11) - 5) * 0.2
        candles.append({
            "timestamp": stamp.isoformat(), "open": close - 0.1,
            "high": close + 0.4, "low": close - 0.4, "close": close,
            "volume": 100 + index,
        })
    path.write_text(json.dumps({"session_date": day.isoformat(), "candles": candles}))


def test_audit_builds_causal_features_and_report(tmp_path):
    cache = tmp_path / "cache"
    output = tmp_path / "output"
    cache.mkdir()
    _cache(cache / "2026-09-28.json", date(2026, 9, 28))
    _cache(cache / "2026-09-29.json", date(2026, 9, 29), 20)

    report = MODULE.run(cache, output)
    assert report["source"]["sessions"] == 2
    assert report["source"]["five_minute_rows"] == 150
    assert report["source"]["indicator_ready_rows"] > 100
    assert report["schema"]["internal_indicator_gaps_after_ready"] == 0
    assert (output / "indicator-feature-matrix.csv").is_file()
    assert (output / "report.json").is_file()
    assert report["safety"]["live_strategy_modified"] is False


def test_strict_slope_states_treat_small_change_as_flat():
    assert MODULE.slope_state(0.11, 0.10) == "SLOPING_UP"
    assert MODULE.slope_state(-0.11, 0.10) == "SLOPING_DOWN"
    assert MODULE.slope_state(0.10, 0.10) == "FLAT"
    assert MODULE.slope_state(0.0, 0.10) == "FLAT"


def test_labels_do_not_use_indicator_columns():
    source = (ROOT / "scripts/audit_hilega_indicator_dataset_v2.py").read_text()
    body = source.split("def label_rows", 1)[1].split("def feature_rows", 1)[0]
    assert "rsi9" not in body
    assert "ema3_rsi" not in body
    assert "wma21_rsi" not in body
