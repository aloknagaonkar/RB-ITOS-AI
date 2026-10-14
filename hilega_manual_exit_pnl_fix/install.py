import ast,datetime,json,shutil
from pathlib import Path
import argparse
ROOT=Path.cwd();HERE=Path(__file__).resolve().parent

def change(text,old,new,path):
 if text.count(old)!=1:raise ValueError(f'{path}: expected one supported anchor, found {text.count(old)}; no files changed')
 return text.replace(old,new,1)
def changes():
 result={}
 core=Path('backend/market_lab/hilega_manual_exit_v1.py');t=(ROOT/core).read_text()
 t=change(t,"manual_exit_confirmed=True,terminal=True))", "manual_exit_confirmed=True,terminal=True,timestamp=stamp(worker)))",core)
 result[core]=t
 path=Path('backend/market_lab/hilega_upstox_sandbox_basket_v2.py');t=(ROOT/path).read_text()
 if 'apply_manual_exit_pnl' in t:raise ValueError('Manual P&L display fix already installed')
 anchor="        trade=trades.setdefault(trade_id,dict(trade_id=trade_id,session_date=en['session_date']"
 t=change(t,anchor,"        from .hilega_manual_exit_pnl_v1 import apply_manual_exit_pnl\n        apply_manual_exit_pnl(leg,en,ex)\n"+anchor,path)
 anchor="    opened=[t for t in trades.values() if t['status']!='CLOSED_ACKNOWLEDGED'];closed=[t for t in trades.values() if t['status']=='CLOSED_ACKNOWLEDGED']"
 replacement="""    for t in trades.values():
        entered=[l for l in t['legs'] if l['entry_order_id']]
        if entered and all(l['status']=='CANCELLED_UNFILLED' for l in entered):t['status']='CANCELLED_UNFILLED'
        elif entered and all(l['status'] in {'SELL_FILLED','CANCELLED_UNFILLED','SELL_ACKNOWLEDGED'} for l in entered):t['status']='CLOSED_ACKNOWLEDGED'
        elif any(l['status']=='MANUAL_EXIT_EVIDENCE_INCOMPLETE' for l in entered):t['status']='RECONCILIATION_REQUIRED'
    opened=[t for t in trades.values() if t['status'] not in {'CLOSED_ACKNOWLEDGED','CANCELLED_UNFILLED'}];closed=[t for t in trades.values() if t['status'] in {'CLOSED_ACKNOWLEDGED','CANCELLED_UNFILLED'}]"""
 t=change(t,anchor,replacement,path)
 t=change(t,"if l['exit_order_id'] and l['pnl_rupees'] is not None", "if (l['exit_order_id'] or l['status']=='CANCELLED_UNFILLED') and l['pnl_rupees'] is not None",path)
 t=change(t,"if not l['exit_order_id'] and l['pnl_rupees'] is not None", "if not l['exit_order_id'] and l['status']!='CANCELLED_UNFILLED' and l['pnl_rupees'] is not None",path)
 result[path]=t
 path=Path('frontend/src/hilegaUpstoxSandboxDashboard.tsx');t=(ROOT/path).read_text()
 t=change(t,"const active=trade.status!=='CLOSED_ACKNOWLEDGED';", "const active=!['CLOSED_ACKNOWLEDGED','CANCELLED_UNFILLED'].includes(trade.status);",path)
 t=change(t,"{shortStatus(leg.status)}</td><td>{leg.quantity}</td>","{shortStatus(leg.status)}</td><td>{leg.quantity}{leg.requested_quantity!=null&&<small>{leg.requested_quantity} requested</small>}</td>",path)
 t=change(t,"`${leg.status} · Order acknowledgement is not a fill confirmation`", "`${leg.status} · ${leg.pnl_basis==='CONFIRMED_FILLS'?'Confirmed execution evidence':'Order acknowledgement is not a fill confirmation'}`",path)
 t=change(t,"{trade.missing_pnl_legs?'known-price subtotal':'estimated'}</b>","{trade.missing_pnl_legs?'known-price subtotal':trade.legs.filter((l:any)=>l.entry_order_id).every((l:any)=>l.pnl_basis==='CONFIRMED_FILLS')?'confirmed':'estimated'}</b>",path)
 result[path]=t
 path=Path('backend/market_lab/hilega_directional_candle_ui_v1.py');t=(ROOT/path).read_text()
 anchor='    for record in _read_audit(LIVE_DIRECTIONAL_AUDIT):\n        if record.get("stage") != "DIRECTIONAL_DECISION":'
 t=change(t,anchor,'    manual_audit_records = _read_audit(LIVE_DIRECTIONAL_AUDIT)\n    for record in manual_audit_records:\n        if record.get("stage") != "DIRECTIONAL_DECISION":',path)
 anchor="    ordered = [rows[key] for key in sorted(rows)]"
 t=change(t,anchor,"    from .hilega_manual_exit_decision_v1 import overlay_manual_exit_rows\n    overlay_manual_exit_rows(rows,manual_audit_records,day)\n"+anchor,path)
 result[path]=t
 path=Path('backend/market_lab/hilega_historical_ui_api_v1.py');t=(ROOT/path).read_text()
 t=change(t,'for key in ("price", "points", "entry_price", "entry_time")','for key in ("price", "points", "entry_price", "entry_time", "exit_reason")',path)
 anchor='        "checkpoint": row.get("bar_timestamp"),'
 t=change(t,anchor,anchor+'\n        "audit_row_id": row.get("audit_row_id"),',path)
 anchor='            "source_bar_timestamp": row.get("source_bar_timestamp"),\n            "directional_action": row.get("action"),'
 t=change(t,anchor,anchor+'\n            "manual_exit": row.get("manual_exit"),\n            "manual_exit_source_state": row.get("manual_exit_source_state"),',path)
 result[path]=t
 path=Path('frontend/src/hilegaDecisionTable.tsx');t=(ROOT/path).read_text()
 anchor="  if(kind==='ACTIVE')return `CONTINUE · ${direction}_ACTIVE`"
 replacement="  if(r.strategy?.manual_exit?.status==='REQUESTED')return `${direction} · MANUAL EXIT REQUESTED · WAITING FOR CLOSURE`\n"+anchor
 t=change(t,anchor,replacement,path)
 anchor="    if(label.includes('STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'))"
 t=change(t,anchor,"    if(label.startsWith('MANUAL_EXIT_'))return `${direction} EXIT · MANUAL EXIT`\n"+anchor,path)
 result[path]=t
 helper2=Path('backend/market_lab/hilega_manual_exit_decision_v1.py')
 if (ROOT/helper2).exists():raise ValueError('Manual decision helper already exists; do not reinstall')
 result[helper2]=(HERE/'files'/helper2).read_text()
 helper=Path('backend/market_lab/hilega_manual_exit_pnl_v1.py')
 if (ROOT/helper).exists():raise ValueError('Manual P&L helper already exists; do not reinstall')
 result[helper]=(HERE/'files'/helper).read_text()
 for p,text in result.items():
  if p.suffix=='.py':ast.parse(text,filename=str(p))
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();result=changes()
 print(json.dumps({'status':'VALIDATED','files':[str(x) for x in result]}))
 if a.check:return
 backup=ROOT/'backups'/('manual-exit-pnl-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
 manifest={'existing':[],'new':[]}
 for path in result:
  if (ROOT/path).exists():
   dest=backup/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/path,dest);manifest['existing'].append(str(path))
  else:manifest['new'].append(str(path))
 (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
 done=[]
 try:
  for path,text in result.items():(ROOT/path).parent.mkdir(parents=True,exist_ok=True);(ROOT/path).write_text(text);done.append(path)
 except Exception:
  for path in reversed(done):
   if str(path) in manifest['existing']:shutil.copy2(backup/path,ROOT/path)
   else:(ROOT/path).unlink(missing_ok=True)
  raise
 print(json.dumps({'status':'APPLIED','backup':str(backup)}))
if __name__=='__main__':main()
