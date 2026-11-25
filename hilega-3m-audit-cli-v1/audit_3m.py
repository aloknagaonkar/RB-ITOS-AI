#!/usr/bin/env python3
"""Read-only, version-aware 3-minute decision audit. Standard library only."""
import argparse
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import html
import json
import math
from pathlib import Path
import zipfile
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
DEFAULT_AUDIT = Path('data/live-observation/hilega-directional-v1/step-audit.jsonl')
SIDES = ('BULLISH','BEARISH')
DISCLAIMER = (
    'Recorded checks are authoritative for what the engine evaluated. Calculated '
    'diagnostics describe the candle and are not invented engine rejections. '
    'Initial setup and follow-up routes have different requirements; a PRICE '
    'follow-up may pass with fewer than two fresh strength/gap votes. '
    'RECONSTRUCTED rows are retrospective, not forward entries or broker fills. '
    'A missing evaluation is NOT a failed evaluation. Full audit-chain integrity '
    'is not certified by this display reader.')


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def compare(a,b,operator):
    if not number(a) or not number(b):return None
    return a>b if operator=='>' else a<b


def flag(value):
    return 'PASS' if value is True else 'FAIL' if value is False else 'NOT_EVALUATED'


def fmt(value):
    return f'{value:.4f}'.rstrip('0').rstrip('.') if number(value) else '-' if value is None else str(value)


def evidence_kind(row):
    p=row.get('payload') or {}
    return 'RECONSTRUCTED' if row.get('status')=='RECOVERED' or p.get('reconstructed') is True else 'LIVE_RECORDED'


def decision_time(row):
    p=row.get('payload') or {}
    return str(p.get('decision_timestamp') or '')


def read_snapshot(path,day):
    """Read only the complete-line prefix present when the handle was opened."""
    rows=[]; malformed=0; partial=False; digest=hashlib.sha256(); consumed=0
    with path.open('rb') as stream:
        import os
        stat=os.fstat(stream.fileno());limit=stat.st_size
        while consumed<limit:
            line=stream.readline(limit-consumed)
            if not line:break
            if not line.endswith(b'\n'):
                partial=True;break
            consumed+=len(line);digest.update(line)
            try:row=json.loads(line)
            except (ValueError,UnicodeError):malformed+=1;continue
            if not isinstance(row,dict):malformed+=1;continue
            p=row.get('payload') or {}
            if not isinstance(p,dict):malformed+=1;continue
            stamps=(p.get('decision_timestamp'),p.get('cutoff_timestamp'),row.get('event_time'))
            if row.get('stage')=='DIRECTIONAL_DECISION':
                if str(p.get('decision_timestamp') or '').startswith(day):rows.append(row)
            elif any(str(stamp).startswith(day) for stamp in stamps if stamp):rows.append(row)
    return rows,dict(path=str(path.resolve()),bytes_at_open=limit,complete_prefix_bytes=consumed,
        complete_prefix_sha256=digest.hexdigest(),malformed_lines=malformed,
        incomplete_tail_ignored=partial,chain_verified=False)


def selected_decisions(rows,version,live_only=False):
    decisions=[r for r in rows if r.get('stage')=='DIRECTIONAL_DECISION'
               and decision_time(r) and (r.get('payload') or {}).get('strategy_version')]
    if not decisions:raise ValueError('NO_DIRECTIONAL_DECISIONS_FOR_DATE')
    available=list(dict.fromkeys((r['payload']['strategy_version']) for r in decisions))
    chosen=available[-1] if version=='latest' else version
    selected=[r for r in decisions if r['payload']['strategy_version']==chosen
              and (not live_only or evidence_kind(r)=='LIVE_RECORDED')]
    if not selected:raise ValueError('NO_DECISIONS_FOR_SELECTED_VERSION_OR_EVIDENCE_MODE')
    grouped={}
    for row in selected:grouped.setdefault(decision_time(row),[]).append(row)
    # Keep actual forward evidence when a later restart reconstructs that candle.
    canonical=[]
    for stamp,items in sorted(grouped.items()):
        actual=[r for r in items if evidence_kind(r)=='LIVE_RECORDED']
        canonical.append((actual or items)[-1])
    return chosen,available,canonical,selected


def diagnostics(p,side):
    f=p.get('price_ema_frame') or {}
    indicators=p.get('completed_3m_indicators') or p.get('completed_5m_indicators') or {}
    r=f.get('rsi9',indicators.get('rsi9'))
    e=f.get('ema3_rsi',indicators.get('ema3'))
    w=f.get('wma21_rsi',indicators.get('wma21'))
    pr=f.get('previous_rsi9');pe=f.get('previous_ema3_rsi');pw=f.get('previous_wma21_rsi')
    sign=1 if side=='BULLISH' else -1
    gap=sign*(e-w) if number(e) and number(w) else None
    oldgap=sign*(pe-pw) if number(pe) and number(pw) else None
    strength=sign*(w-pw) if number(w) and number(pw) else None
    checks=dict(
        fresh_alignment=(sign*(r-e)>0 and sign*(e-w)>0) if all(number(x) for x in (r,e,w)) else None,
        directional_gap_positive=gap>0 if gap is not None else None,
        directional_wma_ge_075=strength>=.75 if strength is not None else None,
        gap_expanding=gap>oldgap if gap is not None and oldgap is not None else None,
        close_vs_ema10=compare(f.get('close'),f.get('ema10'),'>' if sign==1 else '<'),
        ema10_slope=compare(f.get('ema10'),f.get('previous_ema10'),'>' if sign==1 else '<'),
        candle_colour=compare(f.get('close'),f.get('open'),'>' if sign==1 else '<'),
        rsi_level=(r>40 if sign==1 else r<60) if number(r) else None,
        rsi_direction=compare(r,pr,'>' if sign==1 else '<'),
        bullish_initial_gap_ge_2=gap>=2 if sign==1 and gap is not None else None)
    votes=[checks[k] for k in ('directional_gap_positive','directional_wma_ge_075','gap_expanding')]
    return dict(open=f.get('open'),high=f.get('high'),low=f.get('low'),close=f.get('close',p.get('nifty_close')),
        ema10=f.get('ema10'),previous_ema10=f.get('previous_ema10'),rsi9=r,previous_rsi9=pr,
        ema3_rsi=e,previous_ema3_rsi=pe,wma21_rsi=w,previous_wma21_rsi=pw,
        directional_gap=gap,previous_directional_gap=oldgap,directional_wma_strength=strength,
        gap_expansion=gap-oldgap if gap is not None and oldgap is not None else None,
        diagnostic_vote_count=sum(v is True for v in votes) if all(v is not None for v in votes) else None,
        checks=checks,failed_diagnostics=[k for k,v in checks.items() if v is False],
        unavailable_diagnostics=[k for k,v in checks.items() if v is None])


def direction_of(event):
    return 'BEARISH' if 'BEARISH' in str(event.get('event_type','')) else 'BULLISH'


def side_report(row,side):
    p=row['payload'];diag=diagnostics(p,side)
    main=[c for c in p.get('wma_gap_checks') or [] if c.get('direction')==side]
    monitor=p.get('opposite_confirmation') or {}
    monitored=[c for c in monitor.get('checks') or [] if c.get('direction')==side]
    events=[e for e in p.get('event_details') or [] if direction_of(e)==side]
    entered=any(str(e.get('event_type','')).startswith('ENTRY') for e in events)
    # A bullish reversal entry may be confirmed by the separate monitor, while
    # the ordinary entry gate is occupied by the bearish trade.
    use_monitor=bool(monitored and (not main or (entered and not any(c.get('status')=='ENTRY' for c in main))))
    attempts=monitored if use_monitor else main
    check=attempts[-1] if attempts else {}
    channel='BULLISH_REVERSAL_MONITOR' if use_monitor else 'ENTRY_GATE'
    frame=check.get('ema10_entry') or {}
    reasons=list(dict.fromkeys((check.get('reasons') or [])+(frame.get('reasons') or [])))
    status='ENTRY_CONFIRMED' if entered else (('MONITOR_' if use_monitor else '')+str(check.get('status'))) if check else 'NOT_EVALUATED'
    phase='FOLLOWUP' if frame.get('followup_rule') else 'INITIAL_FRAME' if frame else 'STRENGTH_GATE_ONLY' if check else 'NO_CANDIDATE_CHECK'
    context=[]
    if not check:
        context.append('No candidate confirmation evaluation recorded for this side.')
        before=p.get('trade_owner_before');after=p.get('trade_owner_after')
        exiting=any('EXIT' in str(e.get('event_type','')) for e in p.get('event_details') or [])
        if before in SIDES and before==after and not exiting:
            context.append('Regular entry gate is occupied by the existing '+before+' trade; reversal monitor is separate.')
        if diag['checks']['fresh_alignment'] is False:
            context.append('Fresh-setup R/E/W alignment is absent (calculated from the recorded frame).')
        context.append('Watch permission/manual-control details are not fully recorded; no further rejection is invented.')
    flags={k:check.get(k) for k in ('gap_positive_pass','wma_threshold_pass','gap_expanding_pass',
        'strength_gap_pass','strength_gap_evidence_available','confirmation_window_pass')}
    flags.update({k:frame.get(k) for k in ('passed','price_position_pass','slope_pass',
        'candle_colour_pass','rsi_continuation_pass','fresh_signal_alignment_pass',
        'bullish_signal_gap_pass','full_wma_pass','followup_colour_pass',
        'followup_rsi_direction_pass','followup_price_pass','fresh_strength_gap_pass',
        'signal_close_comparison_pass','signal_midpoint_comparison_pass')})
    return dict(decision=decision_time(row),candle=p.get('bar_timestamp'),side=side,
        strategy_version=p.get('strategy_version'),evidence=evidence_kind(row),sequence=row.get('sequence'),
        owner_before=p.get('trade_owner_before'),owner_after=p.get('trade_owner_after'),
        canonical_state=p.get('bullish_state' if side=='BULLISH' else 'bearish_state'),
        pending_after=p.get('pending_candidates') or {},setup_attempts=[s for s in p.get('setup_attempts') or [] if s.get('direction')==side],
        status=status,channel=channel,phase=phase,recorded_blockers=reasons,
        recorded_vote_count=check.get('strength_gap_pass_count'),
        recorded_minimum_votes=check.get('strength_gap_min_passes'),
        route=frame.get('entry_confirmation_route'),signal_available=check.get('signal_available_at'),
        reference_signal_time=frame.get('signal_time'),followup_due=frame.get('followup_due'),
        bullish_full_wma_magnitude=frame.get('full_wma_magnitude'),
        recorded_flags=flags,diagnostics=diag,context=context,
        main_attempts=main,reversal_monitor_attempts=monitored,
        trade_events=events,exit_validation=p.get('exit_validation'),
        canonical_conditions=p.get('canonical_bullish_conditions' if side=='BULLISH' else 'canonical_bearish_conditions'),
        policy_events=p.get('policy_events') or [])


def csv_row(view):
    out={k:v for k,v in view.items() if k not in {'diagnostics','recorded_flags','main_attempts',
        'reversal_monitor_attempts','policy_events','canonical_conditions','exit_validation'}}
    out.update({k:v for k,v in view['diagnostics'].items() if k not in {'checks','failed_diagnostics','unavailable_diagnostics'}})
    out.update({'recorded_'+k:flag(v) for k,v in view['recorded_flags'].items()})
    out.update({'diagnostic_'+k:flag(v) for k,v in view['diagnostics']['checks'].items()})
    out.update(diagnostic_failures=view['diagnostics']['failed_diagnostics'],
        recorded_attempts=view['main_attempts'],reversal_monitor_attempts=view['reversal_monitor_attempts'],
        exit_validation=view['exit_validation'])
    return {k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in out.items()}


def detailed_text(row,views):
    p=row['payload'];frame=p.get('price_ema_frame') or {}
    current=p.get('completed_3m_indicators') or p.get('completed_5m_indicators') or {}
    lines=[f"\n{decision_time(row)[11:16]} IST | candle {str(p.get('bar_timestamp'))[11:16]} | {evidence_kind(row)} | sequence {row.get('sequence')}",
        '  O/H/L/C: '+' / '.join(fmt(frame.get(k)) for k in ('open','high','low','close')),
        '  RSI9='+fmt(frame.get('rsi9',current.get('rsi9')))+' prev='+fmt(frame.get('previous_rsi9'))+
        ' | EMA3(RSI)='+fmt(frame.get('ema3_rsi',current.get('ema3')))+
        ' | WMA21(RSI)='+fmt(frame.get('wma21_rsi',current.get('wma21')))+
        ' | EMA10='+fmt(frame.get('ema10'))+' prev='+fmt(frame.get('previous_ema10')),
        '  OWNER: '+str(p.get('trade_owner_before'))+' -> '+str(p.get('trade_owner_after'))]
    for v in views:
        lines.append('  '+v['side']+' | '+v['status']+' | '+v['channel']+' | '+v['phase']+
            ' | recorded votes='+fmt(v['recorded_vote_count'])+' | route='+str(v['route']))
        lines.append('    RECORDED BLOCKERS (last attempt): '+('; '.join(v['recorded_blockers']) or 'NONE RECORDED'))
        lines.append('    RECORDED FLAGS: '+', '.join(k+'='+flag(value) for k,value in v['recorded_flags'].items()))
        lines.append('    DIAGNOSTICS ONLY: '+', '.join(k+'='+flag(value) for k,value in v['diagnostics']['checks'].items()))
        lines.append('    Gap='+fmt(v['diagnostics']['directional_gap'])+' | WMA strength='+fmt(v['diagnostics']['directional_wma_strength'])+
            ' | expansion='+fmt(v['diagnostics']['gap_expansion'])+' | bullish full WMA='+fmt(v['bullish_full_wma_magnitude']))
        lines.extend('    CONTEXT: '+text for text in v['context'])
        if v['setup_attempts']:lines.append('    SETUP ATTEMPTS: '+json.dumps(v['setup_attempts']))
        if v['pending_after']:lines.append('    PENDING AFTER CANDLE: '+json.dumps(v['pending_after']))
        if len(v['main_attempts'])>1 or v['reversal_monitor_attempts']:
            lines.append('    ALL RECORDED ATTEMPTS: '+json.dumps(dict(entry_gate=v['main_attempts'],reversal_monitor=v['reversal_monitor_attempts'])))
        for event in v['trade_events']:
            lines.append('    TRADE EVENT: '+json.dumps(event))
    if p.get('exit_validation'):lines.append('  EXIT CHECK: '+json.dumps(p['exit_validation']))
    return '\n'.join(lines)


def html_report(title,summary,rows,views):
    escape=lambda v:html.escape(str(v))
    cards=[]
    for row in rows:
        stamp=decision_time(row);pair=[v for v in views if v['decision']==stamp]
        heading=stamp[11:16]+' IST | '+evidence_kind(row)
        lines=[]
        for v in pair:
            flags=' '.join('<span class="'+('pass' if value is True else 'fail' if value is False else 'na')+'">'+escape(k)+': '+flag(value)+'</span>' for k,value in v['recorded_flags'].items())
            diagnostic_table='<table><tr><th>Calculated diagnostic</th><th>Result</th></tr>'+''.join('<tr><td>'+escape(k)+'</td><td>'+flag(value)+'</td></tr>' for k,value in v['diagnostics']['checks'].items())+'</table>'
            values=' | '.join(k+'='+fmt(v['diagnostics'].get(k)) for k in ('open','high','low','close','ema10','previous_ema10','rsi9','previous_rsi9','ema3_rsi','wma21_rsi','directional_gap','previous_directional_gap','directional_wma_strength','gap_expansion'))
            lines.append('<h3>'+v['side']+' — '+escape(v['status'])+'</h3><p>'+escape(v['channel']+' / '+v['phase']+' | recorded votes='+fmt(v['recorded_vote_count'])+' | route='+str(v['route']))+'</p><p><b>Recorded blockers:</b> '+escape('; '.join(v['recorded_blockers']) or 'None recorded')+'</p><p>'+escape(' '.join(v['context']))+'</p><p>'+flags+'</p><p>'+escape(values)+'</p><details><summary>Calculated candle diagnostics — not recorded rejections</summary>'+diagnostic_table+'</details><details><summary>Full values and all recorded attempts</summary><pre>'+escape(json.dumps(v,indent=2))+'</pre></details>')
        cards.append('<section><h2>'+escape(heading)+'</h2>'+''.join(lines)+'<details><summary>Original selected audit record</summary><pre>'+escape(json.dumps(row,indent=2))+'</pre></details></section>')
    return '<!doctype html><meta charset="utf-8"><title>'+escape(title)+'</title><style>body{font:15px/1.5 system-ui;margin:24px;color:#182a38;background:#f3f6f9}section{background:white;padding:16px;margin:16px 0;border:1px solid #ccd5dd;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.pass{color:#146635}.fail{color:#b12624}.na{color:#667788}span{display:inline-block;padding:4px 8px;margin:3px;border:1px solid #ddd}summary{cursor:pointer;padding:8px}</style><h1>'+escape(title)+'</h1><p>'+escape(DISCLAIMER)+'</p><pre>'+escape(json.dumps(summary,indent=2))+'</pre>'+''.join(cards)


def coverage(day,now,start,end,selected):
    target=date.fromisoformat(day)
    beginning=datetime.combine(target,time(9,18),tzinfo=IST)
    closing=datetime.combine(target,time(15,30),tzinfo=IST)
    until=min(now,closing)
    expected=[beginning+timedelta(minutes=3*i) for i in range(125)]
    expected=[at.isoformat() for at in expected if at<=until and start<=at.time()<=end]
    return dict(completed_boundaries_as_of_snapshot=len(expected),
        boundaries_not_present_in_selected_snapshot=[at for at in expected if at not in selected],
        coverage_note='Absence can reflect a selected evidence filter or processing lag; it is not automatically a strategy failure.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day',default=datetime.now(IST).date().isoformat())
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--version',default='latest')
    parser.add_argument('--live-only',action='store_true')
    parser.add_argument('--from-time',default='09:15')
    parser.add_argument('--to-time',default='15:30')
    parser.add_argument('--detail',action='store_true')
    parser.add_argument('--out',type=Path,default=Path('/tmp/hilega-3m-audits'))
    args=parser.parse_args();day=date.fromisoformat(args.day).isoformat()
    start=time.fromisoformat(args.from_time);end=time.fromisoformat(args.to_time)
    if start>end:parser.error('from-time must not exceed to-time')
    if start.tzinfo or end.tzinfo:parser.error('Use local IST HH:MM clocks, without timezone offsets')
    path=args.audit if args.audit is not None else args.repo/DEFAULT_AUDIT
    snapshot_at=datetime.now(IST)
    rows,source=read_snapshot(path,day)
    version,available,canonical,all_selected=selected_decisions(rows,args.version,args.live_only)
    canonical=[r for r in canonical if start<=datetime.fromisoformat(decision_time(r)).astimezone(IST).time()<=end]
    if not canonical:raise ValueError('NO_DECISIONS_IN_REQUESTED_TIME_RANGE')
    views=[side_report(row,side) for row in canonical for side in SIDES]
    now=datetime.now(IST);stamp=now.strftime('%Y%m%dT%H%M%S%f')
    output=args.out.resolve()/(day+'-'+stamp);output.mkdir(parents=True,exist_ok=False)
    selected_times={decision_time(r) for r in canonical}
    raw=[r for r in all_selected if decision_time(r) in selected_times]
    supplementary=[r for r in rows if (r.get('payload') or {}).get('strategy_version')==version
                   and r.get('stage') in {'DIRECTIONAL_SESSION_CUTOFF','DIRECTIONAL_MANUAL_EXIT_RESET','DIRECTIONAL_LIVE_BOOTSTRAP'}]
    summary=dict(session_date=day,strategy_version=version,available_versions=available,
        snapshot_at=snapshot_at.isoformat(),report_generated_at=now.isoformat(),decision_count=len(canonical),
        first_decision=decision_time(canonical[0]),last_decision=decision_time(canonical[-1]),
        live_recorded=sum(evidence_kind(r)=='LIVE_RECORDED' for r in canonical),
        reconstructed=sum(evidence_kind(r)=='RECONSTRUCTED' for r in canonical),
        duplicate_records_retained_in_json=len(raw)-len(canonical),
        recorded_entry_events=sum(str(e.get('event_type','')).startswith('ENTRY') for r in canonical for e in r['payload'].get('event_details') or []),
        recorded_blocker_rows=sum(bool(v['recorded_blockers']) for v in views),
        no_evaluation_rows=sum(v['status']=='NOT_EVALUATED' for v in views),
        live_only=args.live_only,requested_window=[args.from_time,args.to_time],source=source,
        application_files_modified=False,services_restarted=False,broker_requests_sent=False)
    summary.update(coverage(day,snapshot_at,start,end,selected_times))
    groups={}
    for row in raw:groups.setdefault(decision_time(row),[]).append(row)
    duplicate_groups=[dict(decision=at,records=[dict(sequence=r.get('sequence'),
        evidence=evidence_kind(r),record_hash=r.get('record_hash')) for r in items])
        for at,items in groups.items() if len(items)>1]
    data=dict(summary=summary,interpretation=DISCLAIMER,decisions=canonical,side_details=views,
              all_matching_decision_records=raw,duplicate_groups=duplicate_groups,
              supplementary_records=supplementary)
    (output/'audit.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    flat=[csv_row(v) for v in views]
    fields=list(dict.fromkeys(k for row in flat for k in row))
    with (output/'audit.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(flat)
    detail=DISCLAIMER+'\n'+json.dumps(summary,indent=2)+'\n'+'\n'.join(detailed_text(r,[v for v in views if v['decision']==decision_time(r)]) for r in canonical)
    if supplementary:detail+='\n\nSUPPLEMENTARY BOOTSTRAP / MANUAL RESET / SESSION CLOSE RECORDS\n'+json.dumps(supplementary,indent=2)
    (output/'audit.txt').write_text(detail+'\n')
    (output/'audit.html').write_text(html_report('Hilega 3-minute audit — '+day,summary,canonical,views))
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.iterdir()):z.write(p,p.name)
    print(DISCLAIMER+'\n')
    print(json.dumps(summary,indent=2))
    if args.detail:print(detail)
    else:
        print('\nTime | Evidence | Side | Actual status | Channel | Audit votes | Route | Recorded blockers / context')
        for v in views:
            reason='; '.join(v['recorded_blockers']) or (' '.join(v['context']) if v['status']=='NOT_EVALUATED' else 'NONE RECORDED')
            print(' | '.join((v['decision'][11:16],v['evidence'],v['side'],v['status'],v['channel'],fmt(v['recorded_vote_count']),str(v['route']),reason)))
    print('\nDETAIL TEXT:',output/'audit.txt')
    print('CSV:',output/'audit.csv')
    print('HTML:',output/'audit.html')
    print('UPLOAD ZIP:',archive)


if __name__=='__main__':
    main()
