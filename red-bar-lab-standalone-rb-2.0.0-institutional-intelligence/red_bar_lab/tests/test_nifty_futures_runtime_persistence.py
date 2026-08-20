from types import SimpleNamespace

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.nifty_futures_readiness import (
    assess_nifty_futures_readiness,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)


def test_complete_runtime_readiness_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_BAR_ARTIFACTS_ROOT", str(tmp_path))
    contract = SimpleNamespace(
        status="READY",
        instrument_key="NSE_FO|58072",
        trading_symbol="NIFTY FUT",
        expiry="2026-08-25",
    )
    market = SimpleNamespace(
        status="READY",
        instrument_key="NSE_FO|58072",
        latest_timestamp="2026-08-20T10:01:00+05:30",
        latest_close=24290.5,
        latest_volume=7475.0,
        latest_oi=11992825.0,
        candle_readiness=SimpleNamespace(status="READY"),
        volume_authority=SimpleNamespace(status="APPLICABLE"),
    )
    positioning = SimpleNamespace(
        status="READY",
        state="LONG_BUILDUP",
        price_change=2.0,
        price_change_pct=0.05,
        oi_change=1000.0,
        oi_change_pct=0.06,
        relative_volume=1.3,
        baseline_volume=1000.0,
        baseline_samples=20,
    )

    result = assess_nifty_futures_readiness(
        contract=contract,
        market=market,
        positioning=positioning,
    )

    assert result.status == "READY"
    rows = read_nifty_futures_snapshots(RedBarSettings.from_env().database_path)
    assert len(rows) == 1
    assert rows[0]["positioning_state"] == "LONG_BUILDUP"
    assert rows[0]["strength"] == "STRONG"


def test_non_runtime_readiness_without_timestamp_does_not_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_BAR_ARTIFACTS_ROOT", str(tmp_path))

    assess_nifty_futures_readiness(
        contract=SimpleNamespace(status="READY"),
        market=SimpleNamespace(
            status="READY",
            latest_oi=1,
            candle_readiness=SimpleNamespace(status="READY"),
            volume_authority=SimpleNamespace(status="APPLICABLE"),
        ),
        positioning=SimpleNamespace(status="READY", state="NEUTRAL"),
    )

    assert read_nifty_futures_snapshots(RedBarSettings.from_env().database_path) == []
