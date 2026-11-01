"""Exact source transformations; writes only to a new staging directory."""
import hashlib
from pathlib import Path

SOURCE='backend/market_lab/hilega_preparation_runtime_v1/source.py'
WORKER='scripts/hilega_production_simulator_bridge.py'
GUARD='backend/market_lab/hilega_exclusive_closed_route_v1.py'


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('EXACT_STAGE_ANCHOR_REQUIRED')
    return text.replace(old,new,1)


def transformed(source,worker,coordinator,guard):
    source=replace_once(source,'    def run_source_once(self,path):',
        '    @exclusive_source_guard\n    def run_source_once(self,path):')
    source='from market_lab.hilega_exclusive_closed_route_v1 import exclusive_source_guard\n'+source
    worker=replace_once(worker,'                result=bridge.run_source_once(a.source)',
        '                result=closed_poll(bridge,a.source)')
    worker='from market_lab.hilega_exclusive_closed_route_v1 import closed_poll\n'+worker
    anchor='        self.providers,self.clock,self.buffer,self.checkpoint=providers,clock,fee_buffer_cents,checkpoint'
    coordinator=replace_once(coordinator,anchor,anchor+'\n        from market_lab.hilega_exclusive_closed_route_v1 import exclusive_coordinator_guard\n        self.tick=exclusive_coordinator_guard(type(self).tick).__get__(self,type(self))')
    guard=replace_once(guard,"STAGED_SOURCE_SHA256='__STAGED_SOURCE_SHA256__'",
        "STAGED_SOURCE_SHA256='"+hashlib.sha256(source.encode()).hexdigest()+"'")
    return {SOURCE:source,WORKER:worker,'closed_application_coordinator_v1.py':coordinator,GUARD:guard}


def stage(repo,folder,destination):
    texts=transformed((repo/SOURCE).read_text(),(repo/WORKER).read_text(),
        (repo/'hilega-durable-coordinator-v1/closed_application_coordinator_v1.py').read_text(),
        (folder/'exclusive_closed_route_v1.py').read_text())
    destination.mkdir(mode=0o700,exist_ok=False)
    for name,text in texts.items():
        compile(text,str(destination/name),'exec')
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    return {name:hashlib.sha256(text.encode()).hexdigest() for name,text in texts.items()}
