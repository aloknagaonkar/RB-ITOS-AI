"""Compare two completed independent replay directories, never pair by assumed trade ID."""
import argparse,json
from pathlib import Path

def points(p):return sum(t['points'] for t in p['trades'])
def trades(p):
 return '<br>'.join(f"{t['entry_time'][11:16]}–{t['exit_time'][11:16]} · {t['points']:+.2f} ({t.get('route','EXISTING')})" for t in p) or '—'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--old-root',type=Path,required=True);ap.add_argument('--new-root',type=Path,required=True);a=ap.parse_args()
 summary=['# Strict body cross versus BODY50','', 'Gross NIFTY points; research only. Both retain the existing route. No live changes. New rule: body >60% of range and actual open/close straddle of EMA10; removed >50% body-beyond condition. Other checks retained. No post-entry midpoint protection in this comparison.','', '| Date | Deployed | Old BODY50 combined | New body-cross combined | New minus old |','|---|---:|---:|---:|---:|']
 signal=['# Signal-wise comparison','', 'Times IST. Setup identities can change with position state; a dash is not proof of rejection.','', '| Date | Direction | Setup | Deployed | Old BODY50 | New body cross |','|---|---|---|---|---|---|']
 values=['# New variant signal and entry values','', '| Date | Direction | Setup | Entry–exit | Points | Route | O / H / L / C | EMA10 / prior EMA10 | Body % / beyond % | RSI9 / EMA3 RSI / WMA21 | 1m close / breakout level |','|---|---|---|---|---:|---|---|---|---|---|---|']
 total=[0,0,0];complete=0;issues=[]
 for path in sorted(a.new_root.glob('????-??-??.json')):
  n=json.loads(path.read_text());old=a.old_root/path.name;day=path.stem
  if n.get('status')!='COMPLETE' or not old.exists():issues.append(day+': incomplete or old result missing');continue
  o=json.loads(old.read_text())
  if o.get('status')!='COMPLETE':issues.append(day+': old incomplete');continue
  base=n['policies']['DEPLOYED_5M'];oldbase=o['policies']['DEPLOYED_5M']
  sig=lambda p:sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in p['trades'])
  if sig(base)!=sig(oldbase):issues.append(day+': baseline mismatch; excluded');continue
  ps=[base,o['policies']['BODY50_1M_WAIT'],n['policies']['BODY50_1M_WAIT']];v=[points(p) for p in ps]
  complete+=1;total=[x+y for x,y in zip(total,v)]
  summary.append(f'| {day} | {v[0]:+.2f} | {v[1]:+.2f} | {v[2]:+.2f} | {v[2]-v[1]:+.2f} |')
  identities=sorted({(t['direction'],t.get('setup') or '') for p in ps for t in p['trades']})
  for side,setup in identities:
   cells=[trades([t for t in p['trades'] if t['direction']==side and (t.get('setup') or '')==setup]) for p in ps]
   signal.append('| '+' | '.join([day,side,setup[11:16],*cells])+' |')
  for t in ps[2]['trades']:
   e=t.get('evidence') or {};f=e.get('signal_frame') or t.get('entry_evidence') or {};fmt=lambda v:'—' if v is None else f'{v:.3f}'
   cell=lambda keys:' / '.join(fmt(f.get(k)) for k in keys)
   values.append('| '+' | '.join([day,t['direction'],(t.get('setup') or '')[11:16],t['entry_time'][11:16]+'–'+t['exit_time'][11:16],f"{t['points']:+.2f}",t.get('route','EXISTING'),cell(('open','high','low','close')),cell(('ema10','previous_ema10')),' / '.join(fmt(e[k]*100) if k in e else '—' for k in ('body_ratio','body_beyond_ema')),cell(('rsi9','ema3_rsi','wma21_rsi')),fmt((t.get('followup') or {}).get('close'))+' / '+fmt(e.get('low' if t['direction']=='BEARISH' else 'high'))])+' |')
 summary+=['',f'Compared sessions: {complete}. Total deployed {total[0]:+.2f}; old {total[1]:+.2f}; new {total[2]:+.2f}; change {total[2]-total[1]:+.2f}.','',*issues]
 for name,lines in [('three-policy-summary.md',summary),('three-policy-signals.md',signal),('new-signal-values.md',values)]: (a.new_root/name).write_text('\n'.join(lines)+'\n')
 print('\n'.join(summary))
 if issues or not complete:raise SystemExit(2)
if __name__=='__main__':main()
