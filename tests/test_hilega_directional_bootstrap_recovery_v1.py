from __future__ import annotations
from datetime import date, datetime, timedelta
from pathlib import Path
import json

from market_lab.domain import HistoricalCandle, IST
from market_lab.hilega_directional_live_shadow_v1 import HilegaDirectionalLiveShadowCoordinatorV1, UNDERLYING

D = date(2026, 9, 24)

class RecoverySources:
    def __init__(self):
        self._rows = []
        ts = datetime(2026, 9, 24, 9, 15, tzinfo=IST)
        for i in range(15):
            px = 23000.0 + i
            self._rows.append(HistoricalCandle(
                provider="upstox", instrument_key=UNDERLYING, session_date=D,
                interval_seconds=60, timestamp=ts + timedelta(minutes=i),
                open=px, high=px+1, low=px-1, close=px+0.5,
                volume=0, open_interest=0,
            ))
    def warmup_candles(self, session_date, cache_root): return []
    def nifty_intraday_1m(self, *, now=None): return list(self._rows)
    def option_contracts(self, underlying, expiry): return []
    def option_intraday_1m(self, instrument_key): return []

def directional_rows(path: Path):
    rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return [x for x in rows if x.get("stage")=="DIRECTIONAL_DECISION"]

def test_bootstrap_writes_missing_directional_checkpoints_once(tmp_path: Path):
    audit=tmp_path/"audit.jsonl"; health=tmp_path/"health.jsonl"
    now=datetime(2026,9,24,9,30,30,tzinfo=IST)
    first=HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=RecoverySources(), option_expiry=None,
        step_audit_path=audit, health_path=health, warmup_calendar_days=0,
    )
    r1=first.bootstrap(now)
    rows1=directional_rows(audit)
    assert len(rows1)==3
    assert r1["recovered_checkpoint_count"]==3
    assert all(x["status"]=="RECOVERED" for x in rows1)
    assert all((x.get("payload") or {}).get("reconstructed") is True for x in rows1)
    assert all((x.get("payload") or {}).get("recovery_source")=="BOOTSTRAP_RECOVERY" for x in rows1)

    second=HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=RecoverySources(), option_expiry=None,
        step_audit_path=audit, health_path=health, warmup_calendar_days=0,
    )
    r2=second.bootstrap(now)
    rows2=directional_rows(audit)
    assert len(rows2)==3
    assert r2["recovered_checkpoint_count"]==0

def test_bootstrap_does_not_duplicate_existing_live_checkpoint(tmp_path: Path):
    audit=tmp_path/"audit.jsonl"; health=tmp_path/"health.jsonl"
    now=datetime(2026,9,24,9,30,30,tzinfo=IST)
    live=HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=RecoverySources(), option_expiry=None,
        step_audit_path=audit, health_path=health, warmup_calendar_days=0,
    )
    from market_lab.hilega_milega_historical_replay_v1 import aggregate_exact_5m
    bars=aggregate_exact_5m(RecoverySources()._rows,D)
    decision=live.directional.on_bar(bars[0])
    live._audit_directional_decision(now=now,bar=bars[0],decision=decision,status="PROCESSED")

    restarted=HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=RecoverySources(), option_expiry=None,
        step_audit_path=audit, health_path=health, warmup_calendar_days=0,
    )
    r=restarted.bootstrap(now)
    rows=directional_rows(audit)
    assert len(rows)==3
    assert r["recovered_checkpoint_count"]==2
    cps=[x.get("checkpoint") for x in rows]
    assert len(cps)==len(set(cps))
