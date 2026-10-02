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
            coord=HilegaMilegaLiveShadowCoordinatorV1(market_sources=sources,option_expiry=option_expiry)
            while True:
                now=datetime.now(IST)
                if not in_session(now):time.sleep(5);continue
                if now.second>=30:coord.process(now)
                time.sleep(5)
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
