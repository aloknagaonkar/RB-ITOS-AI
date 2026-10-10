"""Project tested replay evidence for the shared audit UI; no strategy decisions."""
from copy import deepcopy
import json
from . import hilega_v2_alignment_replay_v1 as engine

def step(label, result, value, requirement, explanation):
    return dict(label=label,status='INFO' if result is None else 'PASS' if result else 'FAIL',value=value,requirement=requirement,explanation=explanation)

def inspection(a):
    out=[]
    completed=a.get('completed_5m_indicators')
    if completed:out.append(step('Completed five-minute indicators',None,f'RSI {completed.get("rsi9")} · EMA {completed.get("ema3")} · WMA {completed.get("wma21")}', 'Setup uses completed five-minute evidence', 'Minute gap checks are provisional; the indicator timeframe is not changed.'))
    change=(a.get('five_minute_changes') or {}).get('wma21')
    if change is not None:out.append(step('Five-minute WMA change',None,change,'Diagnostic only','This tested policy has no mandatory five-minute slope gate.'))
    for c in a.get('checks') or []:
        side=c['direction']; previous=c.get('previous_timestamp');current=c.get('minute_timestamp')
        pair=f'{previous or "Not available"} → {current}'
        out += [step(f'{side} · confirmation window',c.get('confirmation_window_pass'),c.get('signal_available_at'),'Ten-minute window','Signal availability is distinct from candle label.'),
          step(f'{side} · WMA strength',c.get('wma_threshold_pass'),f'previous {c.get("previous_directional_wma_strength")} → current {c.get("directional_wma_strength")}','>= 0.75',pair),
          step(f'{side} · positive gap',c.get('gap_positive_pass'),f'previous {c.get("previous_gap")} → current {c.get("current_gap")}','> 0','Bullish EMA−WMA; bearish WMA−EMA, on RSI9.'),
          step(f'{side} · gap expansion',c.get('gap_expanding_pass'),f'previous {c.get("previous_gap")} → current {c.get("current_gap")}; delta {c.get("gap_delta")}','> 0 versus adjacent minute',pair),
          step(f'{side} · later persistence',c.get('persistence_pass'),f'armed {c.get("armed_at")}; previous strength {c.get("previous_directional_wma_strength")}','Previous/current >=0.75 and later confirmation','Arm candle does not confirm itself; recorded exit-boundary exception is explicit.'),
          step(f'{side} · evaluation result',c.get('status')=='ENTRY',c.get('status'),'All entry gates pass',' · '.join(c.get('reasons') or []) or 'All recorded gates passed')]
    v=a.get('exit_validation')
    if v:
        out += [step('Five-minute RSI exit warning',v['rsi_opposite'],v['rsi9'],'Opposite WMA21','Initial warning; not sufficient alone.'),
                step('Five-minute EMA exit confirmation',v['ema_opposite'],f'EMA {v["ema3"]}; WMA {v["wma21"]}','EMA also opposite WMA21','Equality waits.'),
                step('Actual dual exit',v['dual_exit_pass'],v['direction'],'Both opposite at completed 5m close','14:55 cutoff is a separate forced exit.')]
    if not out:out=[step('Minute monitoring',None,a.get('owner_after'),'Wait for a setup / monitor active position','No pending entry gate was evaluated at this checkpoint.')]
    return out

def project_session(data, minute_rows=None):
    x=deepcopy(data);reports=[];previous=None;origin=None;entry_price=None;side=None;source=None
    minute_rows=minute_rows or {}
    for i,a in enumerate(x.get('audit') or []):
        cp=a['checkpoint']; ind=a.get('indicators') or {};prev=previous or {}
        checks=a.get('checks') or [];pending_side=checks[0]['direction'] if checks else None
        setup=next((s for s in x.get('setup_attempts',[]) if s['time']==cp),None)
        transitions=a.get('transitions') or []
        # Separate rows in recorded order, keeping the actual timestamp unchanged.
        actions=transitions or [None]
        for j,t in enumerate(actions):
            is_entry=t is not None and t['event']=='ENTRY_ACTIVE';is_exit=t is not None and t['event']=='EXIT_CLOSED'
            if is_entry:
                origin=cp;entry_price=t['price'];side=t['direction']
                trade=next((z for z in x.get('trades',[]) if z['entry_time']==cp and z['direction']==side),{})
                source=trade.get('setup_source','V2_SETUP')
            direction=t['direction'] if t else side or pending_side or (setup or {}).get('direction')
            emitted=[]
            if t:
                event='ENTRY_V2_ALIGNMENT' if is_entry else 'V2_DUAL_EXIT'
                emitted=[event]
                ts=[dict(event_type=event,event_time=cp,price=t['price'],points=t.get('points'),source=source,
                         exit_reason=t.get('reason') or ('SESSION_CUTOFF_1455' if a.get('minute_timestamp')==cp else 'BOTH_RSI9_EMA3_OPPOSITE_WMA21') if is_exit else None,
                         details={'original_entry_time':origin,'original_entry_price':entry_price})]
            else:
                ts=[]
                expired=any('WINDOW_EXPIRED' in c.get('reasons',[]) for c in checks)
                emitted=['WMA_GAP_NO_ENTRY_BY_T10'] if expired else ['WMA_GAP_WAIT'] if checks or setup else []
            before=direction if is_exit else 'NONE' if is_entry else a.get('owner_before','NONE')
            after='NONE' if is_exit else direction if is_entry else a.get('owner_after','NONE')
            candle=deepcopy(minute_rows.get(a.get('minute_timestamp'),{}))
            if not candle:candle={'close':t['price'] if t else a.get('nifty_close')}
            # A cutoff uses the exact 14:55 open, not that minute's later close.
            if is_exit and a.get('minute_timestamp')==cp:candle={'open':t['price'],'close':t['price']}
            r=dict(checkpoint=cp,audit_row_id=f'{cp}:{i}:{j}',audit_sequence=j,linked_signal_bar=origin,
              bar=candle,indicators={'rsi9':ind.get('rsi9'),'ema3_rsi':ind.get('ema3'),'wma21_rsi':ind.get('wma21'),
                'previous_rsi9':prev.get('rsi9'),'previous_ema3_rsi':prev.get('ema3'),'previous_wma21_rsi':prev.get('wma21')},
              strategy={'strategy_id':engine.MODEL,'direction':direction,'decision_timestamp':cp,'owner_before':before,'owner_after':after,
                'state_before':f'{before}_ACTIVE' if before!='NONE' else 'IDLE','state_after':f'{after}_ACTIVE' if after!='NONE' else 'IDLE',
                'events_emitted':emitted,'selected_route':source or (setup or {}).get('source'),'original_entry_price':entry_price,
                'rule_description':f'{direction} · '+('V2 ENTRY · strength + persistence + positive expanding gap' if is_entry else 'V2 EXIT · '+str(ts[0]['exit_reason']) if is_exit else 'ACTIVE · dual-exit monitoring' if after!='NONE' else 'SETUP · waiting for entry gates' if checks or setup else 'NO SIGNAL')},
              transitions=ts,conditions={'authoritative_strategy_steps':True,'strategy_steps':inspection(a)},
              audit_integrity={'decision_timestamp':cp,'chain_ok':None,'evidence_source':engine.SOURCE,'raw_replay_audit':a},
              safety={'observation_only':True,'execution_enabled':False},option_candidate=None,option_lifecycle=None)
            reports.append(r)
            if is_exit:origin=None;entry_price=None;side=None;source=None
        if ind:previous=ind
    x['reports']=reports;x['report_count']=len(reports);x['presentation_version']='shared-replay-ui-1'
    return x

def load_session(day):
    data=engine.load_session(day)
    path=engine.cache_index().get(day)
    rows=json.loads(path.read_text()).get('candles',[]) if path else []
    return project_session(data,{r['timestamp']:r for r in rows})
