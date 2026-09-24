"""Observation-only shadow worker; run alongside market_lab.worker."""
import os,time
from datetime import date,datetime
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from .domain import IST,in_session
from .storage import active_config,make_engine,initialize
from .live_shadow_production_wiring_v1 import LiveShadowProductionCoordinatorV1,floor_5m
from .upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
from .hilega_milega_strategy_v1 import STRATEGY_ID as HILEGA_STRATEGY_ID
from .hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1

def run():
    load_dotenv('.env');engine=make_engine();initialize(engine)
    with Session(engine) as s:config_id,config,enabled=active_config(s)
    if config.provider!='upstox':raise SystemExit('LIVE_SHADOW_PRODUCTION_WIRING_V1 requires provider=upstox')
    sources=UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN',''))
    selected=os.getenv('LIVE_SHADOW_STRATEGY',HILEGA_STRATEGY_ID).strip().upper()
    try:
        if selected==HILEGA_STRATEGY_ID:
            expiry_raw=os.getenv("HILEGA_MILEGA_OPTION_EXPIRY","").strip()
            option_expiry=date.fromisoformat(expiry_raw) if expiry_raw else None
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
                    "strategy_source_sha256":hashlib.sha256(Path(strategy_module.__file__).read_bytes()).hexdigest(),
                    "coordinator_source_sha256":hashlib.sha256(Path(coordinator_module.__file__).read_bytes()).hexdigest(),
                })
                active_sources=evidence
            coord=HilegaMilegaLiveShadowCoordinatorV1(market_sources=active_sources,option_expiry=option_expiry)
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
                        journal.append("process_start", {"session_date":now.date().isoformat()}, {
                            "expiry":option_expiry.isoformat() if option_expiry else None,
                            "strategy_source_sha256":hashlib.sha256(Path(strategy_module.__file__).read_bytes()).hexdigest(),
                            "coordinator_source_sha256":hashlib.sha256(Path(coordinator_module.__file__).read_bytes()).hexdigest(),
                        })
                        coord=HilegaMilegaLiveShadowCoordinatorV1(market_sources=evidence,option_expiry=option_expiry)
                    if now.second>=30:
                        if evidence is not None:
                            evidence.tick(now)
                        coord.process(now)
                    time.sleep(5)
            finally:
                if evidence is not None:
                    evidence.close()
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
