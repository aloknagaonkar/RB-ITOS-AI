from contextlib import asynccontextmanager
from pathlib import Path
import sys
import os
import unittest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE))
sys.path.insert(0,os.environ.get('HILEGA_RSI_TEST_MODULE_ROOT',str(PACKAGE/'files/backend/market_lab')))
import check_api


class ApiProbeTests(unittest.TestCase):
    def test_real_router_http_check_does_not_start_lifespan(self):
        from hilega_rsi_two_route_v1.api import router
        starts=[]
        @asynccontextmanager
        async def lifespan(app):
            starts.append('started')
            raise AssertionError('STAGED_CHECK_MUST_NOT_START_APPLICATION_LIFESPAN')
            yield
        app=FastAPI(lifespan=lifespan)
        app.include_router(router)
        result=check_api.check_app(app)
        self.assertEqual(result['status'],'STAGED_APPLICATION_HTTP_CHECK_PASS')
        self.assertEqual(starts,[])

    def test_missing_route_fails(self):
        with self.assertRaisesRegex(ValueError,'RULES_HTTP_STATUS:404'):
            check_api.check_app(FastAPI())

    def test_wrong_strategy_mode_fails(self):
        app=FastAPI()
        @app.get(check_api.PREFIX+'/rules')
        def rules():return dict(strategy_id='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT',strategy_version='1.0.0',execution_mode='BROKER_EXECUTION')
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):
            check_api.check_app(app)

    def test_missing_workspace_fails(self):
        app=FastAPI()
        @app.get(check_api.PREFIX+'/rules')
        def rules():return dict(strategy_id='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT',strategy_version='1.0.0',execution_mode='SIMULATION_ONLY')
        with self.assertRaisesRegex(ValueError,'WORKSPACE_HTTP_CONTRACT_FAILED'):
            check_api.check_app(app)

if __name__=='__main__':unittest.main()
