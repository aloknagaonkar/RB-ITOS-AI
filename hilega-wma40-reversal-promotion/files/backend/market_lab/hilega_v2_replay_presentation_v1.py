"""Project tested replay evidence for the shared audit UI; no strategy decisions."""
from copy import deepcopy
import json
from . import hilega_combined_replay_v1 as engine

def step(label, result, value, requirement, explanation):
    return dict(label=label,status='INFO' if result is None else 'PASS' if result else 'FAIL',value=value,requirement=requirement,explanation=explanation)

def inspection(a):
    if a.get("policy_id")=="BULLISH_GAP2_FULL_WMA2" or any(c.get("policy_name")=="BULLISH_GAP2_FULL_WMA2" for c in a.get("checks",[])):
        from .hilega_combined_policy_inspection_v1 import inspection as combined_inspection
        return combined_inspection(a)
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
        out += [step('Five-minute RSI exit warning',v.get('rsi_opposite'),v.get('rsi9'),'Opposite WMA21','Initial warning; not sufficient alone.'),
                step('Five-minute EMA exit confirmation',v.get('ema_opposite'),f'EMA {v.get("ema3")}; WMA {v.get("wma21")}','EMA also opposite WMA21','Equality waits.'),
                step('Actual dual exit',v.get('dual_exit_pass'),v.get('direction'),'Both opposite at completed 5m close','14:55 cutoff is a separate forced exit.')]
    if not out:out=[step('Minute monitoring',None,a.get('owner_after'),'Wait for a setup / monitor active position','No pending entry gate was evaluated at this checkpoint.')]
    return out

def project_session(data, minute_rows=None):
    x=deepcopy(data);reports=[];previous=None;origin=None;entry_price=None;side=None;source=None
    for trade in x.get('trades',[]):
        trade['setup_available']=trade.get('signal_time')
        follow=next((e for e in x.get('policy_events',[]) if e.get('time')==trade['entry_time'] and e.get('direction')==trade['direction'] and e.get('passed') and e.get('signal_time')),None)
        trade['qualified_signal_time']=follow.get('signal_time') if follow else None
    minute_rows=minute_rows or {}
    for i,a in enumerate(x.get('audit') or []):
        a=deepcopy(a)
        cp=a['checkpoint'];session_closed=bool(x.get('policy_id')=='BULLISH_GAP2_FULL_WMA2' and cp[11:16]>='14:55')
        if session_closed:a['checks']=[];a['owner_after']='NONE'
        ind=a.get('indicators') or {};prev=previous or {}
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
                emitted=['SESSION_CLOSED'] if session_closed else ['WMA_GAP_NO_ENTRY_BY_T10'] if expired else ['WMA_GAP_WAIT'] if checks or setup else []
            before=direction if is_exit else 'NONE' if is_entry else a.get('owner_before','NONE')
            after='NONE' if is_exit else direction if is_entry else a.get('owner_after','NONE')
            candle=deepcopy(a.get('price_ema_frame') or minute_rows.get(a.get('minute_timestamp'),{}))
            if not candle:candle={'close':t['price'] if t else a.get('nifty_close')}
            # A cutoff uses the exact 14:55 open, not that minute's later close.
            if is_exit and a.get('minute_timestamp')==cp:candle={'open':t['price'],'close':t['price']}
            r=dict(checkpoint=cp,audit_row_id=f'{cp}:{i}:{j}',audit_sequence=j,linked_signal_bar=origin,
              bar=candle,indicators={'rsi9':ind.get('rsi9'),'ema3_rsi':ind.get('ema3'),'wma21_rsi':ind.get('wma21'),
                'previous_rsi9':prev.get('rsi9'),'previous_ema3_rsi':prev.get('ema3'),'previous_wma21_rsi':prev.get('wma21')},
              strategy={'strategy_id':engine.MODEL,'direction':direction,'decision_timestamp':cp,'owner_before':before,'owner_after':after,
                'state_before':f'{before}_ACTIVE' if before!='NONE' else 'IDLE','state_after':'SESSION_LOCKED' if session_closed else f'{after}_ACTIVE' if after!='NONE' else 'IDLE',
                'policy_id':x.get('policy_id'),'strategy_version':x.get('strategy_version'),'events_emitted':emitted,'selected_route':source or (setup or {}).get('source'),'original_entry_price':entry_price,
                'rule_description':('SESSION CLOSED · 14:55 cutoff; no further entries' if session_closed and not is_exit else f'{direction} · '+('Combined ENTRY · completed5m signal + follow-up + bullish gap2/WMA2' if is_entry else 'V2 EXIT · '+str(ts[0]['exit_reason']) if is_exit else 'ACTIVE · dual-exit monitoring' if after!='NONE' else 'SETUP · waiting for entry gates' if checks or setup else 'NO SIGNAL'))},
              transitions=ts,conditions={'authoritative_strategy_steps':True,'strategy_steps':inspection(a)},
              audit_integrity={'decision_timestamp':cp,'chain_ok':None,'evidence_source':x.get('source',engine.SOURCE),'raw_replay_audit':a},
              safety={'observation_only':True,'execution_enabled':False},option_candidate=None,option_lifecycle=None)
            reports.append(r)
            if is_exit:origin=None;entry_price=None;side=None;source=None
        if ind:previous=ind
    x['reports']=reports;x['report_count']=len(reports);x['presentation_version']='shared-replay-ui-1'
    return x

def load_session(day,input_basis='LOCAL'):
    data=validated_session(day) if input_basis=='VALIDATED' else engine.load_session(day)
    path=engine.cache_index().get(day) if input_basis!='VALIDATED' else None
    rows=json.loads(path.read_text()).get('candles',[]) if path else []
    projected=project_session(data,{r['timestamp']:r for r in rows})
    if input_basis=='LOCAL':
        try:
            control=validated_session(day)
            projected['input_comparison']=dict(local_net=round(sum(t['points'] for t in data['trades']),5),validated_net=round(sum(t['points'] for t in control['trades']),5),
                local_trades=[{k:t.get(k) for k in ('direction','entry_time','entry_price','exit_time','exit_price','points')} for t in data['trades']],
                validated_trades=[{k:t.get(k) for k in ('direction','entry_time','entry_price','exit_time','exit_price','points')} for t in control['trades']])
        except (FileNotFoundError,ValueError):pass
    return projected


def validated_session(day):
    """Read the exact parity-tested artifact; never silently fall back to local inputs."""
    from pathlib import Path
    import hashlib
    day=engine.date.fromisoformat(day).isoformat()
    root=Path('data/research/hilega-wma40-promotion-parity') if engine.VERSION.endswith('wma40-reversal') else Path('data/research/hilega-combined-parity-oct16' if day=='2026-10-16' else 'data/research/hilega-combined-parity-historical')
    proof_path=root/'validation.json';artifact=root/(day+'.json')
    if not proof_path.is_file() or not artifact.is_file():raise FileNotFoundError('VALIDATED_REPLAY_NOT_AVAILABLE:'+day)
    proof=json.loads(proof_path.read_text())
    if proof.get('status')!='PASS' or proof.get('strategy_version')!=engine.VERSION:raise ValueError('INVALID_PARITY_PROOF')
    row=next((r for r in proof.get('sessions',[]) if r.get('session_date')==day),None)
    if not row or any(row.get(k)!='PASS' for k in ('research_trade_parity','live_replay_event_parity','shadow_event_dispatch_parity')):raise ValueError('SESSION_PARITY_PROOF_REQUIRED')
    for name,digest in proof.get('implementation_sha256',{}).items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('PARITY_IMPLEMENTATION_CHANGED:'+name)
    if len(proof.get('implementation_sha256',{}))!=3:raise ValueError('IMPLEMENTATION_HASHES_REQUIRED')
    data=json.loads(artifact.read_text())
    if data.get('session_date')!=day or data.get('strategy_version')!=engine.VERSION:raise ValueError('PARITY_ARTIFACT_IDENTITY_MISMATCH')
    total=round(sum(t['points'] for t in data.get('trades',[])),5)
    if len(data.get('trades',[]))!=row['trades'] or total!=round(row['points'],5):raise ValueError('PARITY_ARTIFACT_TOTAL_MISMATCH')
    data['manifest']=dict(data.get('manifest') or {},input_basis='VALIDATED_FROZEN_RESEARCH',parity_report=str(proof_path),warmup_sessions=row.get('warmup_sessions'),recorded_overrides=(data.get('manifest') or {}).get('recorded_overrides',day=='2026-10-16' and not engine.VERSION.endswith('wma40-reversal')))
    return data
