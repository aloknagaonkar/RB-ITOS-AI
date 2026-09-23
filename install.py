#!/usr/bin/env python3
"""Safe, frontend-only Hilega audit table installer. --check before --apply.

Works with the installed independent-session component and existing live page;
never modifies backend, strategy, runtime services or existing evidence.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

NEW={
 'frontend/src/hilegaDecisionTable.tsx',
 'frontend/src/hilegaDecisionTable.css',
 'tests/test_hilega_decision_table_v1.cjs',
}
REPLACE='frontend/src/hilegaHistoricalReplay.tsx'
LIVE='frontend/src/hilegaMilegaShadow.tsx'
PARENT='frontend/src/historicalReplay.tsx'
SECTION_START='    <section className="panel shadow-panel">\n      <div className="panel-heading"><div><h2>Underlying entry / exit activity and decision audit</h2>'


def target_content(repo:Path,patch:Path):
    changes={}
    issues=[]
    for rel in sorted(NEW):
        dest=repo/rel; src=patch/'files'/rel
        if not src.is_file():issues.append(f'Missing patch file: {rel}');continue
        if dest.exists() and dest.read_bytes()!=src.read_bytes():
            issues.append(f'Existing shared component differs: {rel}; do not overwrite manually')
        elif not dest.exists():changes[rel]=src.read_text()
    for rel in [REPLACE,LIVE,PARENT]:
        if not (repo/rel).is_file():issues.append(f'Missing target: {rel}')
    if issues:return changes,issues
    historical=(repo/REPLACE).read_text()
    if 'HilegaDecisionTable' in historical and 'Candle-by-candle mode' in historical:
        print('ALREADY INSTALLED: historical table')
    elif __import__('hashlib').sha256(historical.encode()).hexdigest()=='8e05491ef0d2db0c56475b8adb340596b8069f21429a31df36354f144ac4f6ea':
        changes[REPLACE]=(patch/'files'/REPLACE).read_text()
    else:issues.append('Unknown Hilega historical component; expected installed independent-session version')
    parent=(repo/PARENT).read_text()
    old='<HilegaHistoricalReplay selectedDate={selected} />'
    if parent.count(old)==1:changes[PARENT]=parent.replace(old,'<HilegaHistoricalReplay />',1)
    elif parent.count('<HilegaHistoricalReplay />')!=1:issues.append('Unknown parent Hilega integration')
    live=(repo/LIVE).read_text()
    if 'HilegaDecisionTable' in live and 'Hilega candle-by-candle decision audit' in live:
        print('ALREADY INSTALLED: live audit table')
    elif live.count(SECTION_START)==1 and live.rstrip().endswith('  </div>\n}'):
        start=live.index(SECTION_START)
        end=live.rfind('  </div>\n}')
        if end<=start:issues.append('Could not isolate live activity section')
        else:
            block='''    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Hilega candle-by-candle decision audit</h2>
        <p>Every available five-minute checkpoint; coloured detected, entry and exit rows. Expand for recorded conditions and independent CE lifecycles.</p></div>
        <span className="pill teal">LIVE · OBSERVATION ONLY</span></div>
      <HilegaDecisionTable reports={rows as HilegaAudit[]} mode="LIVE"
        fetchDetail={detailedAudit}
        emptyMessage="No completed live strategy checkpoints available yet." />
    </section>
'''
            live=live[:start]+block+live[end:]
            live=live.replace("import { Fragment, useEffect, useMemo, useState } from 'react'",
              "import { useEffect, useMemo, useState } from 'react'\nimport HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'",1)
            # Previous activity-only expansion is superseded by shared table.
            # Ledger audit still needs detail, expanded and openTradeAudit.
            activity="  const detailBySignal=useMemo(()=>new Map((dashboard?.trades??[]).map(x=>[x.signal_bar,x])),[dashboard])\n"
            live=live.replace(activity,'')
            open_begin='  const openAudit=async(r:AuditReport)=>{'
            open_end='  const openTradeAudit=async(checkpoint:string)=>{'
            if open_begin in live and open_end in live:
                i=live.index(open_begin);j=live.index(open_end,i)
                live=live[:i]+live[j:]
            else:issues.append('Live component audit handlers did not match expected layout')
            # Stable fetch callback ensures 5-second expanded audit refresh works.
            if live.count('const tm=')!=1:issues.append('Unexpected live time helper; cannot safely inject audit accessor')
            else:live=live.replace('const tm=', "const detailedAudit=(cp:string):Promise<HilegaAudit>=>get<AuditReport>('/audit-detail?checkpoint='+encodeURIComponent(cp)) as Promise<HilegaAudit>\nconst tm=",1)
            # Activity remains used for latest entry and latest exit metrics.
            changes[LIVE]=live
    else:issues.append('Unknown live activity section; existing page preserved')
    return changes,issues


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',required=True,type=Path)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true');group.add_argument('--apply',action='store_true')
    a=p.parse_args();repo=a.repo.expanduser().resolve();patch=Path(__file__).resolve().parent
    changes,errors=target_content(repo,patch)
    if errors:
        print('\n'.join('BLOCKED: '+x for x in errors));sys.exit(2)
    print('\n'.join('PATCH: '+x for x in changes) or 'ALREADY INSTALLED: no changes needed')
    if a.check:print('CHECK PASSED; no files changed.');return
    if not changes:print('No changes necessary.');return
    backup=repo/'.hilega-unified-table-backup'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for rel in changes:
        old=repo/rel
        if old.exists():
            out=backup/rel;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,out)
    for rel,content in changes.items():
        out=repo/rel;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(content)
    print('APPLIED. Existing modified files backed up to:',backup)
    print('Frontend-only: no running services, backend files, strategy rules or historical evidence changed.')

if __name__=='__main__':main()
