"""Exercise the existing Hilega HTTP routes without starting application lifespan."""
import json
import time
from fastapi.testclient import TestClient
ID='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
VERSION='rsi-two-route-1.0.0-3m-native-confirmed-midpoint'

def check_app(app):
    client=TestClient(app,base_url='http://127.0.0.1')
    try:
        for attempt in range(50):
            r=client.get('/api/live-shadow/hilega-directional/status?fast=true')
            if r.status_code!=503:break
            detail=r.json().get('detail',{})
            if not isinstance(detail,dict) or detail.get('code')!='UI_AUDIT_CACHE_WARMING_OR_ERROR' or detail.get('error'):break
            time.sleep(.1)
        if r.status_code!=200:raise ValueError('NATIVE_STATUS_HTTP_FAILED:'+str(r.status_code))
        p=r.json()
        if p.get('active_strategy_id')!=ID or p.get('strategy_version')!=VERSION:
            raise ValueError('NATIVE_ACTIVE_STRATEGY_IDENTITY_MISMATCH')
        r=client.get('/api/live-shadow/hilega-historical/sessions')
        if r.status_code!=200:raise ValueError('NATIVE_HISTORICAL_REGISTRY_FAILED')
        if client.get('/api/live-shadow/hilega-rsi-two-route/workspace').status_code==200:
            raise ValueError('SEPARATE_RSI_WORKSPACE_STILL_REGISTERED')
        return dict(status='NATIVE_HILEGA_API_CHECK_PASS',strategy_id=ID,strategy_version=VERSION,lifespan_started=False)
    finally:client.close()
if __name__=='__main__':
    from market_lab.api import app
    print(json.dumps(check_app(app)))
