#!/usr/bin/env python3
from pathlib import Path

p = Path('frontend/src/hilegaMilegaShadow.tsx')
if not p.is_file():
    raise SystemExit('STOP: run from ~/RB-ITOS-AI')

s = p.read_text(encoding='utf-8')
backup = p.with_suffix(p.suffix + '.bak-option-metadata-20260925')
if not backup.exists():
    backup.write_text(s, encoding='utf-8')

marker = 'export default function HilegaMilegaShadow(){'
if 'function attachDirectionalTradeAuditMetadata(' not in s:
    helper = r'''
function sameCheckpoint(a:string|null|undefined,b:string|null|undefined){
  if(!a||!b)return false
  const ams=new Date(a).getTime()
  const bms=new Date(b).getTime()
  if(Number.isFinite(ams)&&Number.isFinite(bms))return ams===bms
  return a===b
}

function attachDirectionalTradeAuditMetadata(
  reports:HilegaAudit[],
  trades:Trade[],
):HilegaAudit[]{
  return reports.map(report=>{
    const trade=(trades??[]).find(t=>sameCheckpoint(t.signal_bar,report.checkpoint))
    if(!trade)return report

    const lifecycleStart={
      model:'DIRECTIONAL_TRADE_DASHBOARD_OVERLAY',
      direction:trade.direction,
      option_side:trade.option_side,
      signal_bar:trade.signal_bar,
      signal_boundary:trade.signal_boundary??null,
      signal_spot:trade.signal_spot??null,
      source:trade.source,
      expiry:trade.expiry,
      atm:trade.atm,
      status:trade.status,
      issue:trade.issue??null,
      active:String(trade.status).toUpperCase()==='ACTIVE',
      latest_completed_minute:trade.legs.map(x=>x.latest_completed_minute).filter(Boolean).at(-1)??null,
      pending_exit_boundary:trade.pending_exit_boundary??null,
      exit_reason:trade.exit_reason??null,
      legs:trade.legs??[],
    }

    const lifecycleExit=trade.exit_reason
      ? {...lifecycleStart,status:trade.status,exit_reason:trade.exit_reason}
      : null

    return {
      ...report,
      strategy:{...(report.strategy??{}),option_side:trade.option_side},
      option_candidate:{
        ...(report.option_candidate??{}),
        model:'DIRECTIONAL_TRADE_DASHBOARD_METADATA',
        direction:trade.direction,
        side:trade.option_side,
        expiry:trade.expiry,
        atm:trade.atm,
        signal_spot:trade.signal_spot??null,
        signal_boundary:trade.signal_boundary??null,
        source:trade.source,
        status:trade.status,
        issue:trade.issue??null,
      },
      option_market_snapshot:{
        ...(report.option_market_snapshot??{}),
        model:'DIRECTIONAL_TRADE_DASHBOARD_METADATA',
        status:trade.status,
        direction:trade.direction,
        side:trade.option_side,
        signal_boundary:trade.signal_boundary??null,
        issue:trade.issue??null,
      },
      option_lifecycle:{
        ...(report.option_lifecycle??{}),
        start:lifecycleStart,
        updates:report.option_lifecycle?.updates??[],
        exit:lifecycleExit,
      },
    } as HilegaAudit
  })
}

'''
    if marker not in s:
        raise SystemExit('STOP: component marker not found')
    s = s.replace(marker, helper + marker, 1)

old = "    merged=overlayDirectionalTradeMarkers(merged,d.trades??[])\n    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')"
new = "    merged=overlayDirectionalTradeMarkers(merged,d.trades??[])\n    merged=attachDirectionalTradeAuditMetadata(merged,d.trades??[])\n    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')"
if old in s:
    s = s.replace(old, new, 1)
elif 'attachDirectionalTradeAuditMetadata(merged,d.trades??[])' not in s:
    raise SystemExit('STOP: refresh overlay block not found')

p.write_text(s, encoding='utf-8')

q = Path('frontend/src/hilegaDecisionTable.tsx')
if not q.is_file():
    raise SystemExit('STOP: missing frontend/src/hilegaDecisionTable.tsx')

t = q.read_text(encoding='utf-8')
qbackup = q.with_suffix(q.suffix + '.bak-option-metadata-20260925')
if not qbackup.exists():
    qbackup.write_text(t, encoding='utf-8')

old_summary = """    <p>Expiry {val(r.option_candidate?.expiry)} · ATM {val(r.option_candidate?.atm)} · Candidate {val(r.option_candidate?.status)} · Market data {visibleSnapshot?val(r.option_market_snapshot?.status):'NOT YET AVAILABLE'}</p>\n    <OptionTable r={r} allowedUntil={allowedUntil} displayKind={displayKind}/>"""
new_summary = """    <p>Expiry {val(r.option_candidate?.expiry)} · ATM {val(r.option_candidate?.atm)} · Lifecycle {val(r.option_lifecycle?.start?.status??r.option_candidate?.status)} · Entry boundary {clock(r.option_lifecycle?.start?.signal_boundary??r.option_candidate?.signal_boundary)}</p>\n    {(r.option_lifecycle?.start?.issue??r.option_candidate?.issue)&&<p className=\"hd-muted\"><b>Exact option data issue:</b> {val(r.option_lifecycle?.start?.issue??r.option_candidate?.issue)}</p>}\n    <OptionTable r={r} allowedUntil={allowedUntil} displayKind={displayKind}/>"""
if old_summary in t:
    t = t.replace(old_summary, new_summary, 1)
elif 'Exact option data issue:' not in t:
    raise SystemExit('STOP: option summary block not found')

q.write_text(t, encoding='utf-8')
print('PATCHED:', p)
print('PATCHED:', q)
print('DONE')
