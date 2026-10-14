"""Export saved session evidence for analysis; no broker calls, orders or service changes."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo

parser=argparse.ArgumentParser()
parser.add_argument('--date',default=datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat())
args=parser.parse_args()
day=datetime.strptime(args.date,'%Y-%m-%d').date().isoformat()
root=Path.cwd()
if not (root/'backend/market_lab').is_dir():raise SystemExit('STOP: run from RB-ITOS-AI repository root')
out=root/'data/research-exports';out.mkdir(parents=True,exist_ok=True)
target=out/f'hilega-session-evidence-{day}-{datetime.now().strftime("%H%M%S")}.zip'
fixed=[
 'data/live-observation/hilega-directional-v1/step-audit.jsonl',
 'data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl',
 'data/live-observation/hilega-upstox-sandbox-v2/control.json',
 'data/live-observation/hilega-upstox-sandbox-v1/would-submit.jsonl',
 'data/live-observation/hilega-upstox-sandbox-v1/live-dispatch.jsonl',
 'data/live-observation/hilega-upstox-sandbox-v1/events.jsonl',
 'data/live-observation/hilega-upstox-sandbox-v1/live-control.json',
 'data/live-observation/shadow-worker-health.json',
 f'data/historical-evidence/hilega-milega-underlying-cache-v1/{day}.json',
 f'data/historical-evidence/hilega-wma-gap-forward-confirmation-v1/sessions/{day}/manifest.json',
]
selected={root/p for p in fixed if (root/p).is_file()}
for relative in ('data/live-observation/hilega-directional-market-evidence-v1','data/live-observation/hilega-market-evidence-v1'):
 base=root/relative
 if base.is_dir():
  for p in base.rglob('*'):
   if p.is_file() and p.suffix in ('.json','.jsonl','.csv') and day in str(p.relative_to(base)):selected.add(p)
for name in ('hilega_wma_gap_live_v2.py','hilega_milega_strategy_v1.py','hilega_bearish_strategy_v1.py','live_shadow_worker_v1.py','hilega_upstox_sandbox_basket_v2.py'):
 p=root/'backend/market_lab'/name
 if p.is_file():selected.add(p)
manifest={'session_date':day,'exported_at':datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(),'files':[],'missing':[p for p in fixed if not (root/p).is_file()],'api_errors':{}}
with ZipFile(target,'x',ZIP_DEFLATED) as archive:
 for p in sorted(selected):
  rel=str(p.relative_to(root));archive.write(p,rel)
  manifest['files'].append({'path':rel,'bytes':p.stat().st_size})
  print('Added:',rel,flush=True)
 for label,url in (
  ('directional-status','/api/live-shadow/hilega-directional/status?fast=true'),
  ('directional-trades','/api/live-shadow/hilega-directional/trade-dashboard'),
  ('v2-evaluations','/api/live-shadow/hilega-directional/wma-gap-evaluations?limit=2000'),
  ('sandbox-dashboard','/api/live-shadow/hilega-upstox-sandbox/dashboard'),
 ):
  print('Reading API:',label,flush=True)
  try:
   with urlopen('http://127.0.0.1:8123'+url,timeout=8) as response:body=json.load(response)
   archive.writestr('api/'+label+'.json',json.dumps(body,indent=2))
  except Exception as e:manifest['api_errors'][label]=type(e).__name__+': '+str(e)
 archive.writestr('export-manifest.json',json.dumps(manifest,indent=2))
print('Created:',target)
print('ZIP size MB:',round(target.stat().st_size/1024/1024,2))
print('Missing optional paths:',len(manifest['missing']))
print('API errors:',manifest['api_errors'])
print('Upload this ZIP for entry/confirmation/exit analysis. Live files and services unchanged.')
