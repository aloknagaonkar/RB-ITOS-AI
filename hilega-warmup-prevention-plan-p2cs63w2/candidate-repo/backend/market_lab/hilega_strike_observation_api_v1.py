"""GET-only observation journal view; sync route runs in FastAPI's threadpool."""
from fastapi import APIRouter
from .hilega_strike_observation_ui_v1 import dashboard

router = APIRouter(prefix='/api/live-shadow/hilega-strike-observation', tags=['hilega-strike-observation'])


@router.get('/dashboard')
def observations():
    return dashboard()
