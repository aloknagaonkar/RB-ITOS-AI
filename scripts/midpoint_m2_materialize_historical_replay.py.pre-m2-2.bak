#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path

V55=Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52=Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON=Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V57=Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")
OUT=Path("data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1")

def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    p=argparse.ArgumentParser(); p.add_argument("--date",default=""); p.add_argument("--limit",type=int,default=0); p.add_argument("--force",action="store_true"); a=p.parse_args()
    v55=load_module(V55,"v55_m2"); v52=load_module(V52,"v52_m2"); canon=load_module(CANON,"canon_m2"); v57=load_module(V57,"v57_m2")
    OUT.mkdir(parents=True,exist_ok=True); indexed={}; written=0
    for block in v52.BLOCKS:
        u,fut,framework=v55.load_block(block,v52,canon)
        for day in sorted(set(u).intersection(fut)):
            if a.date and day!=a.date: continue
            if a.limit and written>=a.limit: break
            d=OUT/day; audit=d/"audit.jsonl"; d.mkdir(parents=True,exist_ok=True)
            if a.force or not audit.exists():
                rows,open_active,active_family=v57.replay_session(day,u[day],fut[day])
                with audit.open("w") as fh:
                    for row in rows: fh.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n")
                meta={"session_date":day,"block":block["name"],"event_count":len(rows),"open_active":bool(open_active),"active_family":active_family,"source":"V57_PARITY_PROVEN_REPLAY"}
                (d/"metadata.json").write_text(json.dumps(meta,indent=2)+"\n"); written+=1
                print(day,"events=",len(rows),"block=",block["name"])
            meta=json.loads((d/"metadata.json").read_text()) if (d/"metadata.json").exists() else {"event_count":sum(1 for _ in audit.open())}
            indexed[day]={"session_date":day,"block":block["name"],"event_count":meta.get("event_count"),"source":"V57_PARITY_PROVEN_REPLAY","status":"AVAILABLE"}
        if a.limit and written>=a.limit: break
    for d in OUT.iterdir():
        if d.is_dir() and (d/"audit.jsonl").exists() and d.name not in indexed:
            meta=json.loads((d/"metadata.json").read_text()) if (d/"metadata.json").exists() else {}
            indexed[d.name]={"session_date":d.name,"block":meta.get("block"),"event_count":meta.get("event_count"),"source":meta.get("source","V57_PARITY_PROVEN_REPLAY"),"status":"AVAILABLE"}
    manifest={"model":"MIDPOINT_UI_REPLAY_MANIFEST_V1","source":"V57_PARITY_PROVEN_REPLAY","session_count":len(indexed),"sessions":sorted(indexed.values(),key=lambda x:x["session_date"],reverse=True)}
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("manifest sessions=",len(indexed))

if __name__=="__main__": main()
