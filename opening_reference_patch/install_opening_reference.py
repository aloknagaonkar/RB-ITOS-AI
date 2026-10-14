"""Run from the RB-ITOS-AI root. Guards source anchors, backs up, then patches."""
from pathlib import Path
import ast, json, shutil, os
from datetime import datetime, timezone
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--repo',default='.')
parser.add_argument('--check',action='store_true',help='Validate anchors without changing files')
a=parser.parse_args();root=Path(a.repo).resolve();backend=root/'backend/market_lab'
helper=Path(__file__).with_name('hilega_opening_reference_v1.py')
marker='from .hilega_opening_reference_v1 import capture_opening_reference, confirmation_reference'
changes={}
def once(text,old,new):
 if text.count(old)!=1:raise RuntimeError('Expected unique source anchor: '+old[:120])
 return text.replace(old,new,1)
for name in ['hilega_alignment_dual_exit_live_v1.py','hilega_v2_alignment_replay_v1.py']:
 path=backend/name;original=path.read_text()
 if marker in original:
  changes[path]=original;continue
 if name=='hilega_alignment_dual_exit_live_v1.py':
  text=once(original,'from .domain import IST','from .domain import IST\n'+marker)
  text=once(text,'        self.canonical.bullish.session=SessionState(session_date=now.date())','        self._opening_reference = capture_opening_reference(self.canonical, now.date())\n        self.canonical.bullish.session=SessionState(session_date=now.date())')
  text=once(text,'        reference=self.canonical.bullish.previous_indicators','        reference=confirmation_reference(self.canonical.bullish.previous_indicators,\n            getattr(self, "_opening_reference", None), t)')
  text=once(text,"'warmup_policy':'HISTORICAL_LOCAL_CACHE_ORDER'","'opening_reference_timestamp':self._opening_reference.bar_timestamp.isoformat() if self._opening_reference else None,\n            'opening_reference_policy':'PRIOR_SESSION_FIRST_CANDLE_ONLY',\n            'warmup_policy':'HISTORICAL_LOCAL_CACHE_ORDER'")
  text=once(text,"        events.extend(entries)","        for check in checks:\n            if getattr(self, '_opening_reference', None) is not None and reference is self._opening_reference.snapshot:\n                check['reference_bar_timestamp'] = self._opening_reference.bar_timestamp.isoformat()\n                check['reference_crosses_session'] = True\n        events.extend(entries)")
 else:
  text=once(original,'from .domain import IST','from .domain import IST\n'+marker)
  text=once(text," day=date.fromisoformat(TARGET);c.bullish.session", " opening_reference=capture_opening_reference(c,date.fromisoformat(TARGET))\n day=date.fromisoformat(TARGET);c.bullish.session")
  text=once(text,'ref=c.bullish.previous_indicators;current=', 'ref=confirmation_reference(c.bullish.previous_indicators,opening_reference,t);current=')
  text=once(text,"checks.extend(cc)","checks.extend(cc)\n  for check in cc:\n   if opening_reference is not None and ref is opening_reference.snapshot:\n    check['reference_bar_timestamp']=opening_reference.bar_timestamp.isoformat()\n    check['reference_crosses_session']=True")
  text=once(text,"engine_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()", "engine_hash=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('hilega_opening_reference_v1.py').read_bytes()).hexdigest()")
 ast.parse(text);changes[path]=text
helper_text=helper.read_text();ast.parse(helper_text);changes[backend/helper.name]=helper_text
for path,text in changes.items():compile(text,str(path),'exec')
print(json.dumps({'status':'VALIDATED','files':[str(p.relative_to(root)) for p in changes]}))
if a.check:raise SystemExit(0)
backup=root/'backups'/('opening-reference-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
for path,text in changes.items():
 if path.exists():shutil.copy2(path,backup/path.name)
for path,text in changes.items():
 tmp=path.with_name(path.name+'.opening-reference.tmp');tmp.write_text(text);os.replace(tmp,path)
print(json.dumps({'status':'APPLIED','backup':str(backup)}))
