"""Queue sandbox exits; request handler never places broker orders."""
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel
from .hilega_upstox_sandbox_basket_v2 import BasketWorker
from .hilega_manual_exit_v1 import request_exit,current,read,state_path
router=APIRouter(prefix='/api/live-shadow/hilega-upstox-sandbox',tags=['hilega-manual-exit'])
class ExitRequest(BaseModel):
 request_id:UUID
 session_date:str
 expected_trade_ids:list[str]
 confirmation:str
@router.get('/manual-exit')
def manual_status():
 w=BasketWorker();c=w.control.read();ids=sorted({r['trade_id'] for r in w.store.open_legs()+w.store.uncertain()})
 return dict(session_date=c.get('session_date'),trade_ids=ids,request=current(w),sandbox_only=True,live_execution_enabled=False)
@router.post('/manual-exit')
def manual_exit(body:ExitRequest):
 if body.confirmation!='EXIT_ALL_SANDBOX_LEGS':raise HTTPException(400,'EXIT_ALL_SANDBOX_LEGS required')
 try:return request_exit(BasketWorker(),request_id=str(body.request_id),session_date=body.session_date,expected_trade_ids=body.expected_trade_ids)
 except ValueError as exc:raise HTTPException(409,str(exc)) from exc
