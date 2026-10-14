"""Guarded additive installer. Run from RB-ITOS-AI root."""
import argparse,ast,datetime,json,shutil,sys
from pathlib import Path
ROOT=Path.cwd();HERE=Path(__file__).resolve().parent

def once(text,old,new,path):
 if text.count(old)!=1:raise ValueError(f'{path}: expected one supported anchor; found {text.count(old)}. No files changed.')
 return text.replace(old,new,1)

def changes():
 result={}
 files=[Path('backend/market_lab/hilega_upstox_sandbox_basket_v2.py'),Path('backend/market_lab/hilega_alignment_dual_exit_live_v1.py'),Path('backend/market_lab/api.py'),Path('frontend/src/hilegaUpstoxSandboxDashboard.tsx')]
 for p in files:
  t=(ROOT/p).read_text()
  if 'hilega_manual_exit' in t or 'HilegaManualExit' in t:raise ValueError(f'{p}: manual exit patch already present; do not reinstall')
  if p.name=='hilega_upstox_sandbox_basket_v2.py':
   t=once(t,"    def close(self):self.analytics.close();self.sandbox.close()",'''    def order_details(self, *, order_id=None, tag=None):
        if not order_id and not tag:raise ValueError('ORDER_ID_OR_TAG_REQUIRED')
        params={'order_id':order_id} if order_id else {'tag':tag}
        data=self._body(self.sandbox.get('/v2/order/details',params=params))['data']
        if not isinstance(data,dict):raise ValueError('INVALID_SANDBOX_ORDER_DETAILS')
        return data
    def cancel_order(self, order_id):
        return self._body(self.sandbox.delete('/v3/order/cancel',params={'order_id':order_id}))
    def close(self):self.analytics.close();self.sandbox.close()''',p)
   t=once(t,"done={r['request_id'] for r in rows if r.get('status')=='ACCEPTED'}", "done={r['request_id'] for r in rows if r.get('status') in {'ACCEPTED','REQUEST_RESOLVED_NO_FILL'}}",p)
   t=once(t,"'ENTRY_BLOCKED','EXIT_BLOCKED'", "'ENTRY_BLOCKED','EXIT_BLOCKED','SKIPPED_MANUAL_EXIT'",p)
   t=once(t,"    def process(self,intent,intents,transport,config):\n", "    def process(self,intent,intents,transport,config):\n        from .hilega_manual_exit_v1 import suppress_intent\n        if suppress_intent(self,intent):return\n",p)
   t=once(t,"        with FileLock(str(self.store.path)+'.worker.lock'):\n", "        with FileLock(str(self.store.path)+'.worker.lock'):\n            from .hilega_manual_exit_v1 import service_manual_exit\n            if service_manual_exit(self):return self.status('MANUAL_EXIT_IN_PROGRESS')\n",p)
   t=once(t,"    def status(self,state='STATUS'):\n", "    def status(self,state='STATUS'):\n        from .hilega_manual_exit_v1 import accepted_order_count\n",p)
   t=once(t,"accepted_orders_this_session=len(rs)", "accepted_orders_this_session=accepted_order_count(self)",p)
  elif p.name=='hilega_alignment_dual_exit_live_v1.py':
   t=once(t,"        self.warning_time = None\n", "        self.warning_time = None\n        self._manual_exit_seen = set()\n",p)
   t=once(t,"        restore=self._restore_audited_option_state(now=now,session_date=now.date())\n", "        restore=self._restore_audited_option_state(now=now,session_date=now.date())\n        from .hilega_manual_exit_strategy_v1 import after_bootstrap\n        after_bootstrap(self,now)\n",p)
   t=once(t,"        before=self.gate.owner;events=[];canonical_decision=None;exit_validation=None;setups=[]\n", "        from .hilega_manual_exit_strategy_v1 import apply_manual_control\n        manual_block=apply_manual_control(self,available,recovered=recovered)\n        before=self.gate.owner;events=[];canonical_decision=None;exit_validation=None;setups=[]\n",p)
   t=once(t,"        entries,checks=self.gate.evaluate(minute=t,current=current,reference=reference,\n", "        if manual_block:self.gate.pending.clear()\n        entries,checks=self.gate.evaluate(minute=t,current=current,reference=reference,\n",p)
  elif p.name=='api.py':
   t=once(t,"from .hilega_upstox_sandbox_dashboard_v1 import router as hilega_upstox_sandbox_dashboard_router\n", "from .hilega_upstox_sandbox_dashboard_v1 import router as hilega_upstox_sandbox_dashboard_router\nfrom .hilega_manual_exit_api_v1 import router as hilega_manual_exit_router\n",p)
   t=once(t,"    app.include_router(hilega_upstox_sandbox_dashboard_router)\n", "    app.include_router(hilega_upstox_sandbox_dashboard_router)\n    app.include_router(hilega_manual_exit_router)\n",p)
  else:
   t="import HilegaManualExit from './hilegaManualExit'\n"+t
   t=once(t,'    <section className="panel shadow-panel"><h2>Current active Sandbox trade</h2>', '    <HilegaManualExit/>\n    <section className="panel shadow-panel"><h2>Current active Sandbox trade</h2>',p)
  result[p]=t
 for source in (HERE/'files').rglob('*'):
  if source.is_file() and source.suffix in {".py",".tsx"} and "__pycache__" not in source.parts:
   p=source.relative_to(HERE/'files')
   if (ROOT/p).exists():raise ValueError(f'{p}: target already exists; refusing overwrite')
   result[p]=source.read_text()
 for p,t in result.items():
  if p.suffix=='.py':ast.parse(t,filename=str(p))
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
 result=changes();print(json.dumps({'status':'VALIDATED','files':[str(x) for x in result]}))
 if a.check:return
 backup=ROOT/'backups'/('manual-exit-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
 manifest={'existing':[],'new':[]}
 for path in result:
  if (ROOT/path).exists():
   target=backup/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/path,target);manifest['existing'].append(str(path))
  else:manifest['new'].append(str(path))
 (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
 written=[]
 try:
  for path,text in result.items():
   target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text);written.append(path)
 except Exception:
  for path in reversed(written):
   if str(path) in manifest['existing']:shutil.copy2(backup/path,ROOT/path)
   else:(ROOT/path).unlink(missing_ok=True)
  raise
 print(json.dumps({'status':'APPLIED','backup':str(backup)}))
if __name__=='__main__':main()
