"""Local PCR observation configuration only; does not modify Hilega or broker orders."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request,urlopen
BASE='http://127.0.0.1:8123/api'
def call(path,body=None):
    req=Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=30) as r:return json.load(r)
state=call('/state?history_limit=1');status=call('/live-shadow/hilega-directional/status')
expiry=(status.get('operational') or {}).get('option_expiry')
today=datetime.now(ZoneInfo('Asia/Kolkata')).date()
try:valid=datetime.strptime(expiry,'%Y-%m-%d').date()>=today
except (TypeError,ValueError):valid=False
if not valid:raise SystemExit('STOP: current Hilega expiry unavailable/expired; no configuration changed')
config=dict(state['config']);config.update(provider='upstox',wings=5,expiry=expiry)
changed=config!=state['config'];paused=False
try:
    if changed:
        call('/collection',{'enabled':False});paused=True
        call('/configurations',config)
    call('/collection',{'enabled':True})
except Exception:
    print('STOP: configuration/enable failed. Inspect Configuration and collection status before retrying.')
    raise
print(json.dumps({'PCR_collection_enabled':True,'provider':'upstox','expiry':expiry,'wings':5,'fixed_anchor_IST':config['anchor_time'],'live_order_sent':False},indent=2))
