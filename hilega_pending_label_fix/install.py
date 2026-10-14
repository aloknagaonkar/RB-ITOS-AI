import argparse,ast,os,shutil
from datetime import datetime,timezone
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--check',action='store_true');a=p.parse_args();root=a.repo.resolve()
api=root/'backend/market_lab/hilega_historical_ui_api_v1.py';ui=root/'frontend/src/hilegaDecisionTable.tsx';helper=Path(__file__).with_name('hilega_pending_direction_display_v1.py')
old='"direction": row.get("owner_after") or row.get("owner_before"),'
new='"direction": __import__("market_lab.hilega_pending_direction_display_v1", fromlist=["resolve_audit_direction"]).resolve_audit_direction(row),'
text=api.read_text()
if new not in text:
 if text.count(old)!=1:raise SystemExit('API direction anchor differs; no files changed')
 text=text.replace(old,new,1)
ast.parse(text);ast.parse(helper.read_text())
front=ui.read_text();anchor="  const explicit=String(r.strategy?.direction??'').toUpperCase()"
insertion="""  // PENDING_DIRECTION_DISPLAY_FIX: audited exclusive flags precede stale/default direction.
  const pendingBullish=r.strategy?.bullish_armed===true
  const pendingBearish=r.strategy?.bearish_armed===true
  if(pendingBearish&&!pendingBullish)return 'BEARISH'
  if(pendingBullish&&!pendingBearish)return 'BULLISH'
  const pendingChecks=list(r.conditions?.wma_gap_checks)
  const pendingDirections=[...new Set(pendingChecks.map((c:any)=>String(c?.direction??'').toUpperCase()).filter((d:string)=>d==='BULLISH'||d==='BEARISH'))]
  if(pendingDirections.length===1)return pendingDirections[0] as 'BULLISH'|'BEARISH'
"""
if 'PENDING_DIRECTION_DISPLAY_FIX' not in front:
 if front.count(anchor)!=1:raise SystemExit('UI direction anchor differs; no files changed')
 front=front.replace(anchor,insertion+anchor,1)
print('VALIDATED: API+table presentation only')
if a.check:raise SystemExit(0)
backup=root/'backups'/('hilega-pending-label-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
changes={api:text,ui:front,api.with_name(helper.name):helper.read_text()}
for path in changes:
 if path.exists():shutil.copy2(path,backup/path.name)
for path,text in changes.items():
 tmp=path.with_name(path.name+'.pending-label.tmp');tmp.write_text(text);os.replace(tmp,path)
print('APPLIED; backup:',backup)
