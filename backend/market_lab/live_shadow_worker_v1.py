"""Observation-only shadow worker; run alongside market_lab.worker."""
import os,time
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from .domain import IST,in_session
from .storage import active_config,make_engine,initialize
from .live_shadow_production_wiring_v1 import LiveShadowProductionCoordinatorV1,floor_5m
from .upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1

def run():
    load_dotenv('.env');engine=make_engine();initialize(engine)
    with Session(engine) as s:config_id,config,enabled=active_config(s)
    if config.provider!='upstox':raise SystemExit('LIVE_SHADOW_PRODUCTION_WIRING_V1 requires provider=upstox')
    sources=UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN',''))
    coord=LiveShadowProductionCoordinatorV1(engine=engine,config_id=config_id,market_sources=sources,events_path='data/live-observation/shadow-v1/events.jsonl',health_path='data/live-observation/shadow-v1/data-health.jsonl')
    last_checkpoint=None
    try:
        while True:
            now=datetime.now(IST)
            if not in_session(now):time.sleep(5);continue
            cp=floor_5m(now)
            if now.second>=30 and cp!=last_checkpoint:coord.process_checkpoint(cp);last_checkpoint=cp
            coord.process_entries_and_open_trades(now);time.sleep(5)
    finally:sources.close()
if __name__=='__main__':run()
