"""Observation-only shadow worker; run alongside market_lab.worker."""
import os,time
import json
from pathlib import Path
from datetime import date,datetime
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from .domain import IST,in_session
from .storage import active_config,make_engine,initialize
from .live_shadow_production_wiring_v1 import LiveShadowProductionCoordinatorV1,floor_5m
from .upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
from .hilega_milega_strategy_v1 import STRATEGY_ID as HILEGA_STRATEGY_ID
from .hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
from .hilega_directional_live_shadow_v1 import (
    STRATEGY_ID as HILEGA_DIRECTIONAL_STRATEGY_ID,
    HilegaDirectionalLiveShadowCoordinatorV1,
)
from .midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1
from .midpoint_strategy.config import live_shadow_config_from_env

HILEGA_UNDERLYING = "NSE_INDEX|Nifty 50"
_component_retry_after = {}


def process_isolated_tick(now, tasks):
    """One observation failure must not starve another strategy. Retry next tick."""
    outcomes = {}
    for name, callback in tasks:
        if now.timestamp() < _component_retry_after.get(name, 0):
            outcomes[name] = "RETRY_BACKOFF"
            continue
        try:
            callback(now)
            outcomes[name] = "OK"
            _component_retry_after.pop(name, None)
        except Exception as exc:
            outcomes[name] = type(exc).__name__
            _component_retry_after[name] = now.timestamp() + 30
            # Do not log broker exception strings, credentials or response bodies.
            print(json.dumps({"stage": "SHADOW_COMPONENT_ERROR", "component": name,
                              "session_date": now.date().isoformat(),
                              "timestamp": now.isoformat(), "error_type": type(exc).__name__}), flush=True)
    path = Path("data/live-observation/shadow-worker-health.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"timestamp": now.isoformat(),
                                   "session_date": now.date().isoformat(),
                                   "components": outcomes}), encoding="utf-8")
    temporary.replace(path)
    return outcomes


def _resolve_hilega_option_expiry(sources, *, session_date: date, configured_raw: str):
    from .hilega_expiry_rollover_v1 import resolve_expiry
    return resolve_expiry(sources, session_date=session_date, configured_raw=configured_raw)


def run():
    load_dotenv('.env');engine=make_engine();initialize(engine)
    with Session(engine) as s:config_id,config,enabled=active_config(s)
    if config.provider!='upstox':raise SystemExit('LIVE_SHADOW_PRODUCTION_WIRING_V1 requires provider=upstox')
    sources=UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN',''))
    selected=os.getenv('LIVE_SHADOW_STRATEGY',HILEGA_STRATEGY_ID).strip().upper()
    try:
        if selected==HILEGA_STRATEGY_ID:
            expiry_raw=os.getenv("HILEGA_MILEGA_OPTION_EXPIRY","").strip()
            option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                sources,
                session_date=datetime.now(IST).date(),
                configured_raw=expiry_raw,
            )
            evidence=None
            evidence_day=None
            active_sources=sources
            if os.getenv("HILEGA_MARKET_EVIDENCE_ENABLED", "0") == "1":
                from pathlib import Path
                from .hilega_market_evidence_v1 import EvidenceJournalV1, RecordingHilegaSourcesV1
                evidence_root=Path(os.getenv("HILEGA_MARKET_EVIDENCE_ROOT", "data/live-observation/hilega-market-evidence-v1"))
                journal=EvidenceJournalV1(evidence_root/(datetime.now(IST).date().isoformat()+".jsonl"))
                evidence=RecordingHilegaSourcesV1(sources,journal)
                evidence_day=datetime.now(IST).date()
                import hashlib
                from . import hilega_milega_strategy_v1 as strategy_module
                from . import hilega_milega_live_shadow_v1 as coordinator_module
                journal.append("process_start", {"session_date":datetime.now(IST).date().isoformat()}, {
                    "expiry":option_expiry.isoformat() if option_expiry else None,
                    "expiry_source":option_expiry_source,
                    "strategy_source_sha256":hashlib.sha256(Path(strategy_module.__file__).read_bytes()).hexdigest(),
                    "coordinator_source_sha256":hashlib.sha256(Path(coordinator_module.__file__).read_bytes()).hexdigest(),
                })
                active_sources=evidence
            coord=HilegaMilegaLiveShadowCoordinatorV1(market_sources=active_sources,option_expiry=option_expiry)
            midpoint_coord=MidpointLiveShadowCoordinatorV1(
                market_sources=sources,
                config=live_shadow_config_from_env(),
            ) if os.getenv("MIDPOINT_SHADOW_ENABLED","0")=="1" else None
            try:
                while True:
                    now=datetime.now(IST)
                    if not in_session(now):time.sleep(5);continue
                    if evidence is not None and now.date()!=evidence_day:
                        # New session starts a new source-tape and a new
                        # coordinator; original audits remain append-only.
                        evidence.close()
                        journal=EvidenceJournalV1(evidence_root/(now.date().isoformat()+".jsonl"))
                        evidence=RecordingHilegaSourcesV1(sources,journal)
                        evidence_day=now.date()
                        option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                            sources,
                            session_date=now.date(),
                            configured_raw=expiry_raw,
                        )
                        journal.append("process_start", {"session_date":now.date().isoformat()}, {
                            "expiry":option_expiry.isoformat() if option_expiry else None,
                    "expiry_source":option_expiry_source,
                            "strategy_source_sha256":hashlib.sha256(Path(strategy_module.__file__).read_bytes()).hexdigest(),
                            "coordinator_source_sha256":hashlib.sha256(Path(coordinator_module.__file__).read_bytes()).hexdigest(),
                        })
                        coord=HilegaMilegaLiveShadowCoordinatorV1(market_sources=evidence,option_expiry=option_expiry)
                    # AUTO_EXPIRY_DAILY_GUARD — independent of evidence recording.
                    if getattr(coord, '_expiry_session_date', None) != now.date():
                        option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                            sources, session_date=now.date(), configured_raw=expiry_raw)
                        coord.option_expiry = option_expiry
                        coord._expiry_session_date = now.date()
                    if now.second>=30:
                        if evidence is not None:
                            evidence.tick(now)
                        coord.process(now)
                        if midpoint_coord is not None:
                            midpoint_coord.process(now)
                    time.sleep(5)
            finally:
                if evidence is not None:
                    evidence.close()
        elif selected==HILEGA_DIRECTIONAL_STRATEGY_ID:
            expiry_raw=os.getenv("HILEGA_MILEGA_OPTION_EXPIRY","").strip()
            option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                sources,
                session_date=datetime.now(IST).date(),
                configured_raw=expiry_raw,
            )
            evidence=None
            evidence_day=None
            active_sources=sources
            if os.getenv("HILEGA_MARKET_EVIDENCE_ENABLED", "0") == "1":
                from pathlib import Path
                import hashlib
                from .hilega_market_evidence_v1 import EvidenceJournalV1, RecordingHilegaSourcesV1
                from . import hilega_directional_coordinator_v1 as directional_module
                from . import hilega_directional_live_shadow_v1 as live_directional_module
                evidence_root=Path(os.getenv("HILEGA_DIRECTIONAL_MARKET_EVIDENCE_ROOT", "data/live-observation/hilega-directional-market-evidence-v1"))
                journal=EvidenceJournalV1(evidence_root/(datetime.now(IST).date().isoformat()+".jsonl"))
                evidence=RecordingHilegaSourcesV1(sources,journal)
                evidence_day=datetime.now(IST).date()
                journal.append("process_start", {"session_date":datetime.now(IST).date().isoformat()}, {
                    "expiry":option_expiry.isoformat() if option_expiry else None,
                    "expiry_source":option_expiry_source,
                    "directional_source_sha256":hashlib.sha256(Path(directional_module.__file__).read_bytes()).hexdigest(),
                    "live_directional_source_sha256":hashlib.sha256(Path(live_directional_module.__file__).read_bytes()).hexdigest(),
                })
                active_sources=evidence
            coord=HilegaDirectionalLiveShadowCoordinatorV1(market_sources=active_sources,option_expiry=option_expiry)
            midpoint_coord=MidpointLiveShadowCoordinatorV1(
                market_sources=sources,
                config=live_shadow_config_from_env(),
            ) if os.getenv("MIDPOINT_SHADOW_ENABLED","0")=="1" else None
            try:
                while True:
                    now=datetime.now(IST)
                    if not in_session(now):time.sleep(5);continue
                    if evidence is not None and now.date()!=evidence_day:
                        evidence.close()
                        journal=EvidenceJournalV1(evidence_root/(now.date().isoformat()+".jsonl"))
                        evidence=RecordingHilegaSourcesV1(sources,journal)
                        evidence_day=now.date()
                        option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                            sources,
                            session_date=now.date(),
                            configured_raw=expiry_raw,
                        )
                        journal.append("process_start", {"session_date":now.date().isoformat()}, {
                            "expiry":option_expiry.isoformat() if option_expiry else None,
                    "expiry_source":option_expiry_source,
                            "directional_source_sha256":hashlib.sha256(Path(directional_module.__file__).read_bytes()).hexdigest(),
                            "live_directional_source_sha256":hashlib.sha256(Path(live_directional_module.__file__).read_bytes()).hexdigest(),
                        })
                        coord=HilegaDirectionalLiveShadowCoordinatorV1(market_sources=evidence,option_expiry=option_expiry)
                    # AUTO_EXPIRY_DAILY_GUARD — independent of evidence recording.
                    if getattr(coord, '_expiry_session_date', None) != now.date():
                        option_expiry, option_expiry_source = _resolve_hilega_option_expiry(
                            sources, session_date=now.date(), configured_raw=expiry_raw)
                        coord.option_expiry = option_expiry
                        coord._expiry_session_date = now.date()
                    if now.second>=30:
                        tasks = []
                        if evidence is not None:tasks.append(("market_evidence", evidence.tick))
                        tasks.append(("hilega", coord.process))
                        if midpoint_coord is not None:
                            tasks.append(("midpoint", midpoint_coord.process))
                        process_isolated_tick(now, tasks)
                    time.sleep(5)
            finally:
                if evidence is not None:evidence.close()
        elif selected in {'LEGACY_ALL3','ALL3_FUTURES_SPOT_LAG_SHADOW_V1'}:
            coord=LiveShadowProductionCoordinatorV1(engine=engine,config_id=config_id,market_sources=sources,events_path='data/live-observation/shadow-v1/events.jsonl',health_path='data/live-observation/shadow-v1/data-health.jsonl')
            last_checkpoint=None
            while True:
                now=datetime.now(IST)
                if not in_session(now):time.sleep(5);continue
                cp=floor_5m(now)
                if now.second>=30 and cp!=last_checkpoint:coord.process_checkpoint(cp);last_checkpoint=cp
                coord.process_entries_and_open_trades(now);time.sleep(5)
        else:
            raise SystemExit(f'Unsupported LIVE_SHADOW_STRATEGY={selected}')
    finally:sources.close()
if __name__=='__main__':run()
