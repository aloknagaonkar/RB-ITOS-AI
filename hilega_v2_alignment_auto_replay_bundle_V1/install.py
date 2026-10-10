"""Guarded installer. Patches historical routing only; rolls back on failure."""
import os,sys,shutil,subprocess
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path.cwd();FILES=Path(__file__).resolve().parent/'files'
def once(text,old,new):
 if new in text:return text
 if text.count(old)!=1:raise RuntimeError('Source differs from expected historical patch anchor: '+old[:100])
 return text.replace(old,new,1)
def patch_api(text):
 old='    try:\n        from .recovered_replay_ui_v1 import load_hilega\n'
 new='    try:\n        if strategy.strip().upper() == "V2_ALIGN":\n            from .hilega_v2_alignment_replay_v1 import load_session as load_alignment\n            return load_alignment(day.isoformat())\n        from .recovered_replay_ui_v1 import load_hilega\n'
 if "load_session as load_alignment, ReplayBusyError" not in text:
  text=once(text,old,new)
 text=once(text,'"sessions": list_sessions(),','"sessions": __import__("market_lab.hilega_v2_alignment_replay_v1", fromlist=["merge_sessions"]).merge_sessions(list_sessions()),')
 old_branch='            from .hilega_v2_alignment_replay_v1 import load_session as load_alignment\n            return load_alignment(day.isoformat())'
 new_branch='            from .hilega_v2_alignment_replay_v1 import load_session as load_alignment, ReplayBusyError\n            try:\n                return load_alignment(day.isoformat())\n            except ReplayBusyError as exc:\n                raise HTTPException(409, str(exc)) from exc\n            except FileNotFoundError as exc:\n                raise HTTPException(404, str(exc)) from exc\n            except ValueError as exc:\n                raise HTTPException(422, str(exc)) from exc'
 text=once(text,old_branch,new_branch)
 return text

def patch_frontend(text):
 text=once(text,"import './hilegaHistoricalReplay.css'", "import HilegaAlignmentReplay from './hilegaAlignmentReplay'\nimport './hilegaHistoricalReplay.css'")
 text=text.replace("'LIVE'|'V1'|'V2'", "'LIVE'|'V1'|'V2'|'V2_ALIGN'") if "'LIVE'|'V1'|'V2'|'V2_ALIGN'" not in text else text
 text=once(text,"fetch(strategyVersion==='V2' ? strategyTestUrl", "fetch(strategyVersion==='V2_ALIGN' ? `${strategyTestUrl}&strategy=V2_ALIGN` : strategyVersion==='V2' ? strategyTestUrl")
 text=text.replace("strategyVersion==='V2'\n          ?", "(strategyVersion==='V2'||strategyVersion==='V2_ALIGN')\n          ?")
 text=text.replace("strategyVersion==='V2' ? Promise.resolve", "(strategyVersion==='V2'||strategyVersion==='V2_ALIGN') ? Promise.resolve")
 text=once(text,"body.strategy_version=strategyVersion==='LIVE'", "body.strategy_version=strategyVersion==='V2_ALIGN' ? body.strategy_version : strategyVersion==='LIVE'")
 text=once(text,'<option value="V2">WMA-gap V2 (historical observation)</option>', '<option value="V2">WMA-gap V2 (historical observation)</option>\n        <option value="V2_ALIGN">V2 — alignment setup + dual exit (research)</option>')
 # Hide legacy trade/audit projections; the new section reads only its own artifact.
 old="      <div className=\"hime-controls\">"
 new="      {strategyVersion==='V2_ALIGN' ? <HilegaAlignmentReplay data={data}/> : <>\n      <div className=\"hime-controls\">"
 text=once(text,old,new)
 text=once(text,'      <div className="hime-review">', '      </>}\n      <div className="hime-review">')
 custom="      {strategyVersion==='V2_ALIGN' ? <HilegaAlignmentReplay data={data}/> : <>\n"
 if custom in text:text=text.replace(custom,'',1)
 marker="      {data?.source==='RECOVERED_HISTORICAL_REPLAY' ?"
 replacement="      {strategyVersion==='V2_ALIGN' ? <HilegaAlignmentReplay data={data} visibleUntil={until} onSelected={setReviewCheckpoint}/> : <>\n"+marker
 text=once(text,marker,replacement)
 return text

def main():
 targets=[Path('backend/market_lab/hilega_historical_ui_api_v1.py'),Path('frontend/src/hilegaHistoricalReplay.tsx')]
 # Prepare all patches before installing, so mismatched source causes no mutation.
 prepared={targets[0]:patch_api((ROOT/targets[0]).read_text()),targets[1]:patch_frontend((ROOT/targets[1]).read_text())}
 paths=[p.relative_to(FILES) for p in FILES.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 paths+=targets
 backup=ROOT/'data/backups'/('hilega-alignment-auto-replay-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
 existed={p:(ROOT/p).exists() for p in paths};backup.mkdir(parents=True)
 try:
  for p in paths:
   if existed[p]:
    dst=backup/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dst)
  for p in paths:
   dst=ROOT/p;dst.parent.mkdir(parents=True,exist_ok=True)
   if p in prepared:dst.write_text(prepared[p])
   elif str(p).startswith('data/') and existed[p]:continue # preserve prior research publication
   else:shutil.copy2(FILES/p,dst)
  env={**os.environ,'PYTHONPATH':str(ROOT/'backend')+os.pathsep+str(ROOT)}
  commands=[[sys.executable,'-m','unittest','discover','-s','tests','-p','test_hilega_v2_alignment_auto_replay.py'],[sys.executable,'-m','py_compile','backend/market_lab/hilega_v2_alignment_replay_v1.py','backend/market_lab/hilega_historical_ui_api_v1.py','scripts/publish_hilega_v2_alignment_replay.py'],['npm','--prefix','frontend','run','build']]
  for cmd in commands:
   print('Running:',*cmd,flush=True);subprocess.run(cmd,cwd=ROOT,env=env,check=True)
 except Exception:
  for p in paths:
   if existed[p]:shutil.copy2(backup/p,ROOT/p)
   elif (ROOT/p).exists():(ROOT/p).unlink()
  print('STOP: source restored. If frontend build started, rebuild prior frontend dist before restarting.');raise
 print('PASS: separate historical V2 alignment + dual-exit replay installed. Restart API after validation. No live strategy, sandbox, service settings or order changed. Backup:',backup)
if __name__=='__main__':main()
