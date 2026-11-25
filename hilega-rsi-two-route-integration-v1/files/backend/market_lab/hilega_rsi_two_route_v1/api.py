"""Strategy-specific read model and offline replay endpoints."""
from datetime import date, datetime
from pathlib import Path
import csv
import io
import json
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from . import STRATEGY_ID, VERSION
from .calendar import IST
from .data import registry, replay
from .live import Store

router=APIRouter(prefix='/api/live-shadow/hilega-rsi-two-route',tags=['RSI Two Route simulation'])

def repo():return Path(os.getenv('HILEGA_RSI_REPO_ROOT',os.getcwd())).resolve()

def checked_day(value):
    try:return date.fromisoformat(value)
    except (ValueError,TypeError):raise HTTPException(400,'DATE_MUST_BE_YYYY_MM_DD') from None

RULES=dict(strategy_id=STRATEGY_ID,strategy_version=VERSION,timeframe='COMPLETED_3_MINUTES',
    warmup_sessions=20,execution_mode='SIMULATION_ONLY',entry_window='ALL_COMPLETED_REGULAR_SESSION_BARS_BEFORE_15:30',
    routes={
        'Normal Route':{'CE':'green AND close > EMA30 High AND at least 2 of RSI5/9/14/21/28 > 55 AND WMA21(RSI9) > 50',
                        'PE':'red AND close < EMA30 Low AND at least 2 of RSI5/9/14/21/28 < 45 AND WMA21(RSI9) < 50'},
        'WMA_bypass':{'CE':'green AND close > EMA30 High AND all 5 RSI > 55; WMA must be available',
                      'PE':'red AND close < EMA30 Low AND all 5 RSI < 45; WMA must be available'}},
    exits={'midpoint':{'CE':'close < original signal (High+Low)/2 AND RSI5 < 50 AND RSI9 < 50',
                       'PE':'close > original signal (High+Low)/2 AND RSI5 > 50 AND RSI9 > 50'},
           'all_three':{'CE':'RSI5 < 50 AND RSI9 < 50 AND WMA21(RSI9) < 50 AND close < EMA30 Low',
                        'PE':'RSI5 > 50 AND RSI9 > 50 AND WMA21(RSI9) > 50 AND close > EMA30 High'},
           'opposite':'fully qualified opposite entry closes existing owner and opens opposite',
           'session':'15:30 exact 15:29 close modeled mark'},
    priority=['SESSION_END','QUALIFIED_OPPOSITE_ENTRY','CONFIRMED_MIDPOINT','ALL_THREE'],
    candle_strength_filter=False,followup_filter=False,first_last_15min_filter=False,
    fill_model='NEXT_1M_OPEN_MODELED; SESSION_END_EXACT_1529_CLOSE',
    costs_included=False,option_premiums_tested=False)

@router.get('/rules')
def rules():return RULES

@router.get('/sessions')
def sessions(start:str='2026-10-01',end:str|None=None):
    try:return dict(strategy_id=STRATEGY_ID,strategy_version=VERSION,
        sessions=registry(repo(),checked_day(start),checked_day(end or str(datetime.now(IST).date()))))
    except ValueError as exc:raise HTTPException(409,str(exc)) from None

@router.post('/replay')
def run_replay(session_date:str):
    try:return replay(repo(),checked_day(session_date))
    except ValueError as exc:raise HTTPException(409,str(exc)) from None

@router.get('/live')
def live(session_date:str|None=None):
    return Store(repo()).view(checked_day(session_date or str(datetime.now(IST).date())))

@router.get('/export.csv')
def export_csv(session_date:str):
    result=run_replay(session_date)
    stream=io.StringIO();writer=csv.writer(stream)
    fields=['route_name','side','entry_signal_time','entry_time','exit_time','entry_price','exit_price','points','peak_positive_points','giveback_points','exit_reasons']
    writer.writerow(fields)
    for t in result['trades']:writer.writerow([t[k] for k in fields])
    return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="rsi-two-route-{checked_day(session_date)}.csv"'})

@router.get('/workspace',response_class=HTMLResponse)
def workspace():return (Path(__file__).with_name('workspace.html')).read_text()
