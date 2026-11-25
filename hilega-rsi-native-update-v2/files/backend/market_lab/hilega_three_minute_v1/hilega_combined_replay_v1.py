"""Combined policy replay. Original legacy engine remains available separately."""
from .hilega_v2_alignment_replay_v1 import *
from .hilega_combined_policy_v1 import RULES,POLICY_ID,VERSION,PriceFrames,make_gate,advance_boundary
MODEL='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT_REPLAY_V1'
SOURCE='RSI_TWO_ROUTE_CONFIRMED_MIDPOINT_REPLAY'
from .warmup import validate_supplied_warmup, warmup_bars, load_warmup
OUTPUT_ROOT=Path('data/historical-evidence/hilega-rsi-native-v1')

def replay(session_date, raw_rows, warmup, metadata=None):
 from ..hilega_rsi_two_route_v1.native_replay import build_session
 return build_session(session_date,raw_rows,warmup,metadata)

import os,tempfile,fcntl

def cache_index(roots=None):
 result={}
 # Later roots take precedence for the same date; recovery stays separate.
 for root in (CACHE_ROOTS if roots is None else roots):
  for p in sorted(Path(root).glob('????-??-??.json')):
   date.fromisoformat(p.stem);result[p.stem]=p
 return result

def source_signature(paths):
 # Read bounded files, never the entire live audit. Changes invalidate the cache.
 hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 engine_hash=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('hilega_opening_reference_v1.py').read_bytes()+Path(__file__).with_name('hilega_combined_policy_v1.py').read_bytes()+Path(__file__).with_name('hilega_v2_alignment_replay_v1.py').read_bytes()).hexdigest()
 namespace_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}
 from ..hilega_rsi_two_route_v1.data import code_hash
 signature=hashlib.sha256(json.dumps({'native_code':code_hash(),'files':hashes,'engine':engine_hash,'namespace':namespace_hashes,'rules':RULES},sort_keys=True).encode()).hexdigest()
 return signature,hashes

def validate_saved(x,day):
 if x.get('model')!=MODEL or x.get('session_date')!=day or x.get('strategy_version')!=VERSION or x.get('execution_enabled') is not False:raise ValueError('INVALID_RESEARCH_ARTIFACT')
 x['reports']=[{'checkpoint':a['checkpoint']} for a in x.get('audit',[])]
 x['report_count']=len(x['reports'])
 return x

def load_session(day,root=None,cache_roots=None):
 day=date.fromisoformat(day).isoformat();output=Path(root or OUTPUT_ROOT)
 index=cache_index(cache_roots)
 if day not in index:raise FileNotFoundError(f'V2 alignment replay: local Nifty 1m candle cache missing for {day}. A listed recorded/research session is not proof of candle availability. Recover candle data before evaluating this date.')
 verified_warmup,coverage=load_warmup(index,date.fromisoformat(day))
 selected=[(d,index[d]) for d,_ in verified_warmup]+[(day,index[day])]
 fingerprint,hashes=source_signature([p for _,p in selected])
 artifact=output/(day+'.json')
 if artifact.is_file():
  x=json.loads(artifact.read_text())
  if (x.get('manifest') or {}).get('auto_input_signature')==fingerprint:
   return validate_saved(x,day)
 output.mkdir(parents=True,exist_ok=True)
 # Cross-process per-date lock: no duplicate replay calculations.
 with (output/(day+'.lock')).open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ReplayBusyError(f'Replay for {day} is already calculating. Retry shortly.')
  # Recheck after acquiring lock.
  if artifact.is_file():
   x=json.loads(artifact.read_text())
   if (x.get('manifest') or {}).get('auto_input_signature')==fingerprint:return validate_saved(x,day)
  warm=[];raw=None
  for d,p in selected:
   data=json.loads(p.read_text())
   if data.get('session_date') not in (None,d):raise ValueError(f'CACHE_SESSION_DATE_MISMATCH:{p}')
   if data.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError(f'CACHE_UNDERLYING_MISMATCH:{p}')
   rr=data.get('candles') or []
   if d==day:raw=rr
   elif rr:warm.append((d,rr))
  warm=verified_warmup
  if not warm:raise ValueError(f'V2 alignment replay: no prior-session indicator warmup for {day}.')
  result=replay(day,raw,warm,{'source':'AUTO_LOCAL_HISTORICAL_CANDLE_REPLAY','auto_input_signature':fingerprint,'source_sha256':hashes,'warmup_first':warm[0][0],'warmup_last':warm[-1][0],'warmup_coverage':coverage,'chart_parity_verified':False})
  # Preserve the previous research artifact before refresh; frozen/live data untouched.
  if artifact.is_file():
   version=hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]
   history=output/'previous-research-versions';history.mkdir(exist_ok=True)
   previous=history/(day+'-'+version+'.json')
   if not previous.exists():previous.write_bytes(artifact.read_bytes())
  with tempfile.NamedTemporaryFile('w',dir=output,delete=False) as f:
   json.dump(result,f,indent=2);tmp=f.name
  os.replace(tmp,artifact)
  return validate_saved(result,day)

def merge_sessions(rows,root=None,cache_roots=None):
 merged={x['session_date']:dict(x) for x in rows};index=cache_index(cache_roots)
 # Keep the same existing date registry. Do not scan/deserialize hundreds of caches.
 for p in sorted(Path(root or OUTPUT_ROOT).glob('????-??-??.json')):
  day=date.fromisoformat(p.stem).isoformat()
  merged.setdefault(day,{'session_date':day,'source':SOURCE,'source_id':f'{SOURCE}:{day}','status':'COMPLETE','evidence_level':'STRATEGY','ce_available':False,'expiry':None,'available_sources':[]})
 for day in index:
  merged.setdefault(day,{'session_date':day,'source':SOURCE,'source_id':f'{SOURCE}:{day}','status':'CANDLES_AVAILABLE','evidence_level':'STRATEGY','ce_available':False,'expiry':None,'available_sources':[]})
 for day,row in merged.items():
  if day in index:row['available_sources']=list(dict.fromkeys([*row.get('available_sources',[]),SOURCE]))
  row['alignment_candle_cache_available']=day in index
 return sorted(merged.values(),key=lambda x:x['session_date'],reverse=True)
