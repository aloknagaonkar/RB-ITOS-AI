#!/usr/bin/env python3
"""Read-only reconciliation of archived V58 trade identities vs current V57 replay."""
import csv, importlib.util
from collections import Counter
from pathlib import Path

ARCHIVE=Path('data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-v58-480-session-be-accounting/trade-accounting-v58.csv')
if not ARCHIVE.is_file(): raise SystemExit(f'STOP: archived V58 trade CSV missing: {ARCHIVE}')

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
v55=load(Path('scripts/midpoint_v55_boundary_selection_replay.py'),'v55_parity')
v52=load(Path('scripts/midpoint_mature_boundary_robustness_v52_1.py'),'v52_parity')
canon=load(Path('scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py'),'canon_parity')
v57=load(Path('scripts/midpoint_v57_full_historical_be_lifecycle_replay.py'),'v57_parity')
with ARCHIVE.open(newline='') as f: old=list(csv.DictReader(f))
key=lambda r:(r['session_date'],r['entry_timestamp'],r['family'],r['direction'])
archived=Counter(key(r) for r in old)
current=Counter(); current_closed=Counter(); blocks=[]
for block in v52.BLOCKS:
    u,fut,_=v55.load_block(block,v52,canon)
    days=sorted(set(u)&set(fut)); b=Counter()
    for day in days:
        audit,_,_=v57.replay_session(day,u[day],fut[day])
        entries=[(i,r) for i,r in enumerate(audit) if r.get('event_type') in ('B_ENTRY','E_ENTRY')]
        for j,(i,r) in enumerate(entries):
            k=key({'session_date':day,'entry_timestamp':r['event_timestamp'],
                   'family':r['family'],'direction':r['direction']})
            current[k]+=1;b[k]+=1
            end=entries[j+1][0] if j+1<len(entries) else len(audit)
            if any(x.get('event_type') in ('CAP20_RESCUE_TRIGGERED','CAP20_SHADOW_EXIT','STRUCTURAL_TERMINAL') for x in audit[i:end]):current_closed[k]+=1
    blocks.append((block['name'],sum(b.values())))
print('Archived V58 entries:',sum(archived.values()),'current replay entries:',sum(current.values()))
print('Archived closed structural:',sum(r.get('structural_terminal','').lower()=='true' for r in old))
print('Current CAP20 or structural closed:',sum(current_closed.values()))
print('Current block counts:',blocks)
missing=archived-current; added=current-archived
print('Only in archived V58:',sum(missing.values()))
for k,n in missing.items():print('  ',n,k)
print('Only in current replay:',sum(added.values()))
for k,n in added.items():print('  ',n,k)
print('No files or live runtime modified.')
