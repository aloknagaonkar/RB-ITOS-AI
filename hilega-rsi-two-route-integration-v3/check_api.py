"""Check mounted endpoint behavior without depending on FastAPI route internals."""
import json

PREFIX='/api/live-shadow/hilega-rsi-two-route'


def check_app(app):
    from fastapi.testclient import TestClient
    # Do not enter `with TestClient(...)`: that would start the application's
    # lifespan and could open databases or start existing companion workers.
    client=TestClient(app,base_url='http://127.0.0.1')
    try:
        response=client.get(PREFIX+'/rules')
        if response.status_code!=200:
            raise ValueError('STAGED_RSI_RULES_HTTP_STATUS:'+str(response.status_code))
        rules=response.json()
        expected={'strategy_id':'HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT',
                  'strategy_version':'1.0.0','execution_mode':'SIMULATION_ONLY'}
        if any(rules.get(k)!=v for k,v in expected.items()):
            raise ValueError('STAGED_RSI_RULES_IDENTITY_MISMATCH')
        response=client.get(PREFIX+'/workspace')
        if (response.status_code!=200 or 'text/html' not in response.headers.get('content-type','')
                or 'RSI Two Route' not in response.text or 'wma21_rsi9_threshold' not in response.text):
            raise ValueError('STAGED_RSI_WORKSPACE_HTTP_CONTRACT_FAILED')
        return dict(status='STAGED_APPLICATION_HTTP_CHECK_PASS',**expected,
                    checked_endpoints=[PREFIX+'/rules',PREFIX+'/workspace'],
                    lifespan_requested=False,worker_start_requested=False,broker_requests_sent=False)
    finally:
        client.close()


def main():
    from market_lab.api import app
    print(json.dumps(check_app(app),indent=2))

if __name__=='__main__':main()
