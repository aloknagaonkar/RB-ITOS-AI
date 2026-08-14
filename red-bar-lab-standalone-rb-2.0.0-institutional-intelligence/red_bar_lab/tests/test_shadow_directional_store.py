from pathlib import Path

from red_bar_lab.services.shadow_directional_store import ShadowDirectionalStore


def test_store_deduplicates_instrument_and_candle(tmp_path: Path):
    store = ShadowDirectionalStore(tmp_path / "shadow.jsonl")
    record = {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "timestamp": "2026-08-13 10:00:00",
        "direction": "BULLISH",
    }
    assert store.append_once(record) is True
    assert store.append_once(record) is False
    assert len(store.read_all()) == 1


def test_store_forces_execution_blocked(tmp_path: Path):
    store = ShadowDirectionalStore(tmp_path / "shadow.jsonl")
    store.append_once({
        "instrument_key": "NSE_INDEX|Nifty 50",
        "timestamp": "2026-08-13 10:00:00",
        "execution_allowed": True,
    })
    row = store.read_all()[0]
    assert row["execution_allowed"] is False


def test_latest_filters_instrument(tmp_path: Path):
    store = ShadowDirectionalStore(tmp_path / "shadow.jsonl")
    store.append_once({"instrument_key": "A", "timestamp": "2026-08-13 10:00:00"})
    store.append_once({"instrument_key": "B", "timestamp": "2026-08-13 10:05:00"})
    assert len(store.latest(instrument_key="A")) == 1
    assert store.latest(instrument_key="A")[0]["instrument_key"] == "A"
