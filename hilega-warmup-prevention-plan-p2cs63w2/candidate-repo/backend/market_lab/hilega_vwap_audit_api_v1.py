from fastapi import APIRouter, HTTPException, Query
from .hilega_vwap_audit_v1 import inspect

router=APIRouter(prefix='/api/live-shadow/hilega-vwap-observation',tags=['hilega-vwap-observation'])


@router.get('/inspection')
def inspection(at:str=Query(...,max_length=64)):
    try:return inspect(at)
    except (ValueError,TypeError):raise HTTPException(422,'Timezone-aware decision timestamp required') from None
