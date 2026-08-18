from datetime import date
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services import red_bar_v2_historical_validation as module
from red_bar_lab.services.red_bar_v2_evidence_collection import RedBarV2EvidenceStore
from red_bar_lab.services.red_bar_v2_historical_validation import (
    RED_BAR_V2_ADAPTER_ID,
    RED_BAR_V2_STRATEGY_ID,
    RED_BAR_V2_VERSION,
    RedBarV2HistoricalStrategyAdapter,
    red_bar_v2_strategy_registry,
)


def _candles():
    timestamps = pd.date_range(
        "2026-08-21 09:15",
        periods=30,
        freq="1min",
        tz="Asia/Kolkata",
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [1000.0] * 30,
        }
    )


def test_registry_exposes_red_bar_v2_in_generic_validation():
    registry = red_bar_v2_strategy_registry()
    definition = registry.get(RED_BAR_V2_STRATEGY_ID, RED_BAR_V2_VERSION)
    assert definition.adapter_id == RED_BAR_V2_ADAPTER_ID
    assert definition.display_name == "Red Bar V2 — RSI/VWAP Reversal"
    assert definition.research_scope == "RESEARCH_ONLY"


def test_adapter_normalizes_candidate_events_and_records_evidence(tmp_path, monkeypatch):
    replay_result = SimpleNamespace(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        admitted_candidates=1,
        blocked_candidates=1,
        final_trade_state="ACTIVE",
        events=(
            SimpleNamespace(
                event_type="CANDIDATE_ADMISSION",
                direction="BULLISH",
                option_side="CE",
                candidate_allowed=True,
                admission_code="INITIAL_BULLISH_ALIGNMENT",
            ),
            SimpleNamespace(
                event_type="CANDIDATE_ADMISSION",
                direction="BEARISH",
                option_side="PE",
                candidate_allowed=False,
                admission_code="ACTIVE_TRADE_BLOCK",
            ),
        ),
    )
    monkeypatch.setattr(module, "replay_red_bar_v2_day", lambda *a, **k: replay_result)

    class Reader:
        def read_day(self, instrument_key, trading_date, interval_minutes=1):
            return _candles()

    store = RedBarV2EvidenceStore(tmp_path)
    adapter = RedBarV2HistoricalStrategyAdapter(Reader(), evidence_store=store)
    result = adapter.run_day("NSE_INDEX|Nifty 50", date(2026, 8, 21))

    assert result.ready is True
    assert result.fidelity == "UNDERLYING_ONLY"
    assert len(result.rows) == 2
    assert result.rows[0].decision == "BULLISH"
    assert result.rows[0].execution == "SHADOW_CE"
    assert result.rows[1].execution == "BLOCKED"
    assert store.paths.replay.exists()
    assert len(store.paths.replay.read_text(encoding="utf-8").splitlines()) == 1


def test_adapter_blocks_when_cached_candles_are_missing(tmp_path):
    class Reader:
        def read_day(self, instrument_key, trading_date, interval_minutes=1):
            return pd.DataFrame()

    adapter = RedBarV2HistoricalStrategyAdapter(
        Reader(),
        evidence_store=RedBarV2EvidenceStore(tmp_path),
    )
    result = adapter.run_day("NIFTY", date(2026, 8, 21))
    assert result.ready is False
    assert result.readiness_reason == "NO_CACHED_ONE_MINUTE_CANDLES"


def test_replay_failure_is_recorded_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module,
        "replay_red_bar_v2_day",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad replay")),
    )

    class Reader:
        def read_day(self, instrument_key, trading_date, interval_minutes=1):
            return _candles()

    store = RedBarV2EvidenceStore(tmp_path)
    adapter = RedBarV2HistoricalStrategyAdapter(Reader(), evidence_store=store)

    try:
        adapter.run_day("NIFTY", date(2026, 8, 21))
    except ValueError:
        pass
    else:
        raise AssertionError("Replay failure must propagate to the validation engine")

    text = store.paths.replay.read_text(encoding="utf-8")
    assert "ValueError:bad replay" in text
