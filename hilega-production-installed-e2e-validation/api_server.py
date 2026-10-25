"""Private loopback-only workspace API for VM validation; never the main API."""
import argparse,os,socket
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--fd',required=True,type=int);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    out=a.output.resolve();db=Path(os.environ['HILEGA_PRODUCTION_SIM_DB']).resolve();key=Path(os.environ['HILEGA_PRODUCTION_CONTROL_TOKEN_FILE']).resolve()
    if db.parent!=out or key.parent!=out:raise ValueError('ISOLATED_PATHS_REQUIRED')
    if os.getenv('HILEGA_PRODUCTION_WORKSPACE_MODE')!='SIMULATION_ONLY' or os.getenv('HILEGA_PRODUCTION_BROKER_OBSERVE')!='0':raise ValueError('ISOLATED_SIMULATION_ONLY_REQUIRED')
    sock=socket.socket(fileno=a.fd)
    if sock.getsockname()[0]!='127.0.0.1':raise ValueError('LOOPBACK_ONLY')
    from fastapi import FastAPI
    from market_lab.hilega_production_workspace_v1 import router,workspace_lifespan
    import uvicorn
    app=FastAPI(lifespan=lambda app:workspace_lifespan());app.include_router(router)
    uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False)).run(sockets=[sock])
if __name__=='__main__':main()
