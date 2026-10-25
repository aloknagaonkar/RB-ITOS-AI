"""VM-only offline parity gate; no broker calls or service operations."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

def signature(trades):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),
        round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in trades)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--reference-root',type=Path,action='append',required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    from market_lab import hilega_combined_replay_v1 as replay
    from market_lab import hilega_combined_policy_v1 as policy
    import inspect
    validator=Path('scripts/validate_hilega_combined_promotion.py')
    spec=importlib.util.spec_from_file_location('original_live_dispatch_validation',validator)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    controls={}
    for root in args.reference_root:
        report=json.loads((root/'report.json').read_text())
        if report['status']!='COMPLETE':raise ValueError('REFERENCE_INCOMPLETE:'+str(root))
        for row in report['sessions']:
            if row['status']!='COMPLETE':raise ValueError('SESSION_INCOMPLETE')
            day=row['session_date'];target=row['policies']['WMA40_EXIT_PLUS_CONFIRMED_REVERSAL']
            if day in controls and signature(controls[day]['trades'])!=signature(target['trades']):
                raise ValueError('CONFLICTING_REFERENCE:'+day)
            controls[day]=target
    with ZipFile(args.input_zip) as z:
        inputs={Path(n).stem:json.loads(z.read(n))['candles'] for n in z.namelist()
            if n.startswith('candles/') and n.endswith('.json')}
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for day,control in sorted(controls.items()):
        raw=inputs[day];warm=[(d,r) for d,r in sorted(inputs.items()) if d<day and r]
        result=replay.replay(day,raw,warm,dict(source='WMA40_RESEARCH_INPUT_ZIP',input_zip=str(args.input_zip),recorded_overrides=False))
        if signature(result['trades'])!=signature(control['trades']):raise ValueError('RESEARCH_PARITY_FAILED:'+day)
        actual_exits,actual_entries=module.live_signature(day,raw,warm)
        expected_exits=sorted((t['entry_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in result['trades'])
        expected_entries=sorted((t['entry_time'],round(t['entry_price'],5)) for t in result['trades'])
        if actual_exits!=expected_exits or actual_entries!=expected_entries:raise ValueError('LIVE_REPLAY_PARITY_FAILED:'+day)
        row=dict(session_date=day,status='PASS',trades=len(result['trades']),warmup_sessions=len(warm),
            points=round(sum(t['points'] for t in result['trades']),5),
            research_trade_parity='PASS',live_replay_event_parity='PASS',shadow_event_dispatch_parity='PASS')
        rows.append(row);print(json.dumps(row),flush=True)
        (args.output/(day+'.json')).write_text(json.dumps(result,indent=2))
    hashes={}
    for name in ('hilega_combined_policy_v1','hilega_combined_replay_v1','hilega_alignment_dual_exit_live_v1'):
        mod=__import__('market_lab.'+name,fromlist=['VERSION'])
        hashes['backend/market_lab/'+name+'.py']=hashlib.sha256(Path(inspect.getfile(mod)).read_bytes()).hexdigest()
    proof=dict(status='PASS',strategy_version=policy.VERSION,sessions=rows,implementation_sha256=hashes,
        input_sha256=hashlib.sha256(args.input_zip.read_bytes()).hexdigest(),orders_sent=False)
    (args.output/'validation.json').write_text(json.dumps(proof,indent=2))
    print('VALIDATION:',args.output/'validation.json')

if __name__=='__main__':main()
