from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path
from typing import Any
RESEARCH_VERSION="MIDPOINT_V2_DEVELOPMENT_SCHEMA_PROBE_V1"
FORBIDDEN={"OOS_E","OOS_F","OOS_G","OOS_H"}
def walk(obj:Any,prefix=""):
    if isinstance(obj,dict):
        for k,v in obj.items():
            path=f"{prefix}.{k}" if prefix else str(k); yield path,v; yield from walk(v,path)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:3]):
            path=f"{prefix}[{i}]"; yield path,v; yield from walk(v,path)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--framework',required=True); ap.add_argument('--output',required=True); args=ap.parse_args()
    doc=json.load(open(args.framework,encoding='utf-8')); events=list(doc.get('events') or [])
    blocks=sorted({str(e.get('block')) for e in events if e.get('block')}); forbidden=sorted(set(blocks)&FORBIDDEN)
    if forbidden: raise SystemExit('Refusing forbidden V2 discovery blocks: '+', '.join(forbidden))
    terms=('midpoint','boundary','reference','high','low','break','timestamp','snapshot','close','candle')
    counts=Counter(); samples={}
    for event in events[:100]:
        for path,value in walk(event):
            if any(t in path.lower() for t in terms):
                norm=path
                for i in range(3): norm=norm.replace(f'[{i}]','[]')
                counts[norm]+=1
                if norm not in samples and not isinstance(value,(dict,list)): samples[norm]=value
    result={'status':'AVAILABLE','research_version':RESEARCH_VERSION,'source':args.framework,'event_count':len(events),'blocks':blocks,'forbidden_blocks_present':forbidden,'candidate_paths':[{'path':p,'count':c,'sample':samples.get(p)} for p,c in counts.most_common(120)],'purpose':'Discover exact development framework field names required to wire V2 BASE_THEN_GO and FAILED_BREAK_RECLAIM without guessing.','governance':{'oos_h_allowed':False,'rule_selection_performed':False,'pnl_analysis_performed':False,'v1_modified':False}}
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8'); print(json.dumps(result,indent=2,allow_nan=False))
if __name__=='__main__': main()
