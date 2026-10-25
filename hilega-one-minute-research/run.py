"""Full1m versus deployed5m offline study. No live source writes or orders."""
import argparse
from datetime import datetime
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('one_min_core',HERE/'timing_core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
MODULES=('hilega_combined_policy_v1','hilega_v2_alignment_replay_v1','hilega_milega_strategy_v1','hilega_milega_bearish_strategy_v1','hilega_directional_coordinator_v1','hilega_opening_reference_v1')

def convert(name,source):
    source=source.replace('timedelta(minutes=5)','timedelta(minutes=1)')
    if name=='hilega_combined_policy_v1':
        for old,new in [('at.minute%5','at.minute%1'),('at.minute//5*5','at.minute//1*1'),('.total_seconds()%300','.total_seconds()%60'),('confirmation_interval_minutes=5','confirmation_interval_minutes=1')]:
            source=source.replace(old,new)
        if any(x in source for x in ('timedelta(minutes=5)','at.minute%5','at.minute//5','%300')):
            raise ValueError('UNCONVERTED_CADENCE')
    if name in ('hilega_milega_strategy_v1','hilega_milega_bearish_strategy_v1'):
        source=source.replace('t == "09:20"','t == "09:16"').replace('t == "09:25"','t == "09:17"')
    if name=='hilega_v2_alignment_replay_v1':source=source.replace('time(14,50)','time(14,54)')
    # Diagnostic labels reflect cadence; numeric RSI/EMA/WMA thresholds stay unchanged.
    source=source.replace('COMPLETED_FIVE_MINUTE','COMPLETED_ONE_MINUTE').replace('PREVIOUS_COMPLETED_FIVE_MINUTE','PREVIOUS_COMPLETED_ONE_MINUTE').replace('5M','1M').replace('5m','1m')
    # Preserve helper import; core.aggregate handles 1m research candles.
    source=source.replace('aggregate_exact_1m','aggregate_exact_5m')
    return source

def isolated_one(root):
    import market_lab
    installed=Path(market_lab.__file__).parent
    for name in MODULES:
        (root/(name+'.py')).write_text(convert(name,(installed/(name+'.py')).read_text()))
    namespace=types.ModuleType('research1m');namespace.__path__=[str(root),str(installed)]
    sys.modules['research1m']=namespace
    return importlib.import_module('research1m.hilega_combined_policy_v1'),importlib.import_module('research1m.hilega_v2_alignment_replay_v1')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if core.policy5.VERSION!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':raise ValueError('DEPLOYED_VERSION_MISMATCH')
    warm,records=core.read_inputs(args.input_zip)
    data=json.loads(args.session_input.read_text());day=data['session_date']
    records=[r for r in records if str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(day)]
    until=datetime.fromisoformat(day+'T14:55:00+05:30')
    args.output.mkdir(parents=True,exist_ok=True)
    print('Running deployed5m control and recorded-live parity...',flush=True)
    five=core.run(core.policy5,core.legacy5,warm,data['candles'],day,5,until)
    proof=core.parity(five,records,until)
    (args.output/'parity.json').write_text(json.dumps(proof,indent=2))
    if proof['status']!='PASS':
        print(json.dumps(proof,indent=2));raise SystemExit('STOP:5M_RECORDED_LIVE_PARITY_FAILED; inspect inputs before comparison')
    print('5m parity PASS. Running isolated1m with1m indicator warmup...',flush=True)
    with tempfile.TemporaryDirectory(prefix='hilega-offline1m-') as directory:
        p,l=isolated_one(Path(directory))
        one=core.run(p,l,warm,data['candles'],day,1,until)
    results={'DEPLOYED_5M':five,'RESEARCH_1M':one}
    lines=['# Full1m versus deployed5m — '+day,'','Recorded-live5m parity: PASS.',
        'Gross NIFTY points, no option fills/costs. All indicators recalculated at selected cadence; periods retain counts, so clock horizons differ.',
        'Same numeric thresholds, original follow-up, bearish WMA40+confirmed bullish reversal,14:55 cutoff. No no-touch bypass or extra exit slopes.',
        'Entry/exit prices are hypothetical boundary marks. No live changes.','',
        '| Policy | Trades | Winning points | Losing points | Net points |','|---|---:|---:|---:|---:|']
    for name,r in results.items():
        trades=r['trades'];win=sum(max(t['points'],0) for t in trades);loss=sum(min(t['points'],0) for t in trades)
        lines.append(f'| {name} | {len(trades)} | {win:+.2f} | {loss:+.2f} | {win+loss:+.2f} |')
    lines+=['','| Policy | Direction | Setup | Qualified | Entry–exit | NIFTY points | Exit reason |','|---|---|---|---|---|---:|---|']
    checks=['# Entry and exit audit','', '| Policy | Time IST | Frame and checks |','|---|---|---|']
    hm=lambda t:t[11:16] if t else '—'
    for name,r in results.items():
        for t in r['trades']:
            lines.append(f"| {name} | {t['direction']} | {hm(t.get('setup'))} | {hm(t.get('qualified'))} | {hm(t['entry_time'])}–{hm(t['exit_time'])} | {t['points']:+.2f} | {t['exit_reason']} |")
        for a in r['audit']:
            if a['checks'] or a['exit_validation']:
                checks.append(f"| {name} | {hm(a['time'])} | {json.dumps(a,sort_keys=True)} |")
    (args.output/'report.json').write_text(json.dumps(dict(session_date=day,baseline_parity=proof,policies=results,orders_sent=False),indent=2))
    (args.output/'comparison.md').write_text('\n'.join(lines)+'\n')
    (args.output/'decision-audit.md').write_text('\n'.join(checks)+'\n')
    print('\n'.join(lines));print('REPORT:',args.output/'report.json')

if __name__=='__main__':main()
