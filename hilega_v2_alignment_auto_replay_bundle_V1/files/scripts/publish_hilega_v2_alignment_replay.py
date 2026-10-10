"""Explicit offline publication to a separate research directory; no broker calls."""
import argparse,json,hashlib,os,tempfile
from pathlib import Path
from datetime import date
from market_lab.hilega_v2_alignment_replay_v1 import replay,OUTPUT_ROOT

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--dates',nargs='+',required=True)
 p.add_argument('--cache-root',type=Path,required=True,help='Directory of YYYY-MM-DD.json one-minute caches')
 p.add_argument('--warmup-root',type=Path,default=Path('data/historical-evidence/hilega-milega-underlying-cache-v1'))
 p.add_argument('--warmup-journal',type=Path,help='Optional immutable warmup journal; first successful response per prior date, reproduces supplied research')
 p.add_argument('--output-root',type=Path,default=OUTPUT_ROOT)
 p.add_argument('--confirm',choices=['PUBLISH_RESEARCH_ONLY'],required=True)
 a=p.parse_args()
 # Restrict writes to this dedicated namespace, preserving other evidence.
 if a.output_root.name!=OUTPUT_ROOT.name:raise ValueError('OUTPUT_MUST_USE_SEPARATE_ALIGNMENT_RESEARCH_DIRECTORY')
 journal=[]
 if a.warmup_journal:
  seen=set()
  for line in a.warmup_journal.open():
   x=json.loads(line)
   if x.get('kind')=='warmup' and x.get('response'):
    d=x['args']['date']
    if d not in seen:journal.append((d,x['response']));seen.add(d)
 for day in sorted(set(a.dates)):
  day=date.fromisoformat(day).isoformat();cache=a.cache_root/(day+'.json')
  raw=json.loads(cache.read_text())['candles'];warm=[];hashes={}
  if a.warmup_journal:
   warm=[(d,rr) for d,rr in journal if d<day];hashes[str(a.warmup_journal)]=sha(a.warmup_journal)
  else:
   for f in sorted(a.warmup_root.glob('????-??-??.json')):
    if f.stem<day:
     rr=json.loads(f.read_text()).get('candles') or []
     if rr:warm.append((f.stem,rr));hashes[str(f)]=sha(f)
  result=replay(day,raw,warm,{'source':'RECONSTRUCTED_BROKER_HISTORICAL','cache_sha256':sha(cache),'warmup_sha256':hashes,'warmup_first':min(d for d,_ in warm) if warm else None,'warmup_last':max(d for d,_ in warm) if warm else None,'chart_parity_verified':False})
  a.output_root.mkdir(parents=True,exist_ok=True)
  with tempfile.NamedTemporaryFile('w',dir=a.output_root,delete=False) as f:
   json.dump(result,f,indent=2);tmp=f.name
  os.replace(tmp,a.output_root/(day+'.json'))
  print(json.dumps({'date':day,'status':'PUBLISHED_RESEARCH_ONLY',**result['performance_summary'][0]}))
if __name__=='__main__':main()
