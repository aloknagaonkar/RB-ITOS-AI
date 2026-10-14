"""Read-only readiness and timings; prints no credentials."""
from urllib.request import urlopen
from urllib.error import HTTPError
from time import monotonic
import json
BASE='http://127.0.0.1:8123/api'
for label,path in [('collector','/state?history_limit=1'),('PCR','/live-shadow/hilega-pcr/context'),('PCR cached','/live-shadow/hilega-pcr/context')]:
 start=monotonic()
 try:
  with urlopen(BASE+path,timeout=15) as r:x=json.load(r)
  print(label,'seconds:',round(monotonic()-start,3))
  if label=='collector':
   c=x.get('config') or {};w=x.get('worker') or {}
   print({k:x.get(k) for k in ('enabled','observation_count','receipt_age_seconds')})
   print('config:',{k:c.get(k) for k in ('provider','expiry','wings')})
   print('worker:',{k:w.get(k) for k in ('state','alive','last_error','last_success_at')})
  else:print({k:x.get(k) for k in ('status','reason','observation_id','available_at','age_seconds','expiry')},'panels:',len(x.get('panels') or []))
 except HTTPError as e:print(label,'HTTP',e.code,e.read().decode()[:500])
 except Exception as e:print(label,type(e).__name__,str(e))
